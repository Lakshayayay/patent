// Thermal + visible-light skin scanner — ESP32-CAM (AI-Thinker) firmware v0.1
//
// Serial commands (115200 baud, type in Serial Monitor or send from Python):
//   s  -> sensor reading (thermal 8x8 + probe temp + GSR) as one JSON line
//   c  -> same as 's' plus a JPEG photo (base64) in the same JSON line
//   w  -> WiFi status (connected, IP, signal strength)
// Web page: http://<ip from the wifi line> shows the live photo, 8x8 heat map and probe temp
//   (/data = reading JSON, /capture.jpg = photo). Viewer must be on the same hotspot.
// Every message is one line of JSON starting with '{'. Ignore any other lines
// (the ESP32 boot ROM prints garbage/text at startup).
//
// Libraries (Arduino Library Manager):
//   Adafruit AMG88xx, Adafruit ADS1X15, OneWire, DallasTemperature
// Board: "AI Thinker ESP32-CAM" (esp32 core by Espressif).

#include "esp_camera.h"
#include "img_converters.h"   // frame2jpg(): software JPEG for sensors without hardware JPEG
#include <Wire.h>
#include <WiFi.h>
#include <WebServer.h>
#include <StreamString.h>
#include <Adafruit_AMG88xx.h>
#include <Adafruit_ADS1X15.h>
#include <OneWire.h>
#include <DallasTemperature.h>
#include "base64.h"

// ---- Pins (see PROJECT_LOG.md for wiring) ----
#define I2C_SDA      13   // AMG8833 + ADS1115 (shared bus)
#define I2C_SCL      15
#define ONEWIRE_PIN  14   // DS18B20 probe, 4.7k pull-up to 3.3V

#define ENABLE_WIFI  true // set false if the board brownout-resets
#if __has_include("secrets.h")
#include "secrets.h"
#endif
#ifndef WIFI_SSID
#define WIFI_SSID    "Lakshay"   // case-sensitive
#endif
#ifndef WIFI_PASS
#define WIFI_PASS    "123456789"
#endif
#define GSR_CHANNEL  0    // ADS1115 A0

// AI-Thinker camera pins
#define PWDN_GPIO_NUM  32
#define RESET_GPIO_NUM -1
#define XCLK_GPIO_NUM   0
#define SIOD_GPIO_NUM  26
#define SIOC_GPIO_NUM  27
#define Y9_GPIO_NUM    35
#define Y8_GPIO_NUM    34
#define Y7_GPIO_NUM    39
#define Y6_GPIO_NUM    36
#define Y5_GPIO_NUM    21
#define Y4_GPIO_NUM    19
#define Y3_GPIO_NUM    18
#define Y2_GPIO_NUM     5
#define VSYNC_GPIO_NUM 25
#define HREF_GPIO_NUM  23
#define PCLK_GPIO_NUM  22

Adafruit_AMG88xx amg;
Adafruit_ADS1115 ads;
OneWire oneWire(ONEWIRE_PIN);
DallasTemperature probe(&oneWire);
WebServer server(80);

bool camOk, amgOk, adsOk, probeOk;

bool initCamera() {
  camera_config_t c = {};
  c.ledc_channel = LEDC_CHANNEL_0;
  c.ledc_timer = LEDC_TIMER_0;
  c.pin_d0 = Y2_GPIO_NUM; c.pin_d1 = Y3_GPIO_NUM; c.pin_d2 = Y4_GPIO_NUM; c.pin_d3 = Y5_GPIO_NUM;
  c.pin_d4 = Y6_GPIO_NUM; c.pin_d5 = Y7_GPIO_NUM; c.pin_d6 = Y8_GPIO_NUM; c.pin_d7 = Y9_GPIO_NUM;
  c.pin_xclk = XCLK_GPIO_NUM;
  c.pin_pclk = PCLK_GPIO_NUM;
  c.pin_vsync = VSYNC_GPIO_NUM;
  c.pin_href = HREF_GPIO_NUM;
  c.pin_sccb_sda = SIOD_GPIO_NUM;
  c.pin_sccb_scl = SIOC_GPIO_NUM;
  c.pin_pwdn = PWDN_GPIO_NUM;
  c.pin_reset = RESET_GPIO_NUM;
  c.xclk_freq_hz = 20000000;
  c.pixel_format = PIXFORMAT_JPEG;
  c.frame_size = FRAMESIZE_QVGA;   // 320x240, plenty for an 8x8 thermal overlay; ~6-10 KB JPEG
  c.jpeg_quality = 12;             // 0-63, lower = better quality / bigger
  c.fb_count = 2;
  c.fb_location = CAMERA_FB_IN_PSRAM;
  c.grab_mode = CAMERA_GRAB_LATEST; // always hand back the freshest frame, not a stale one
  if (esp_camera_init(&c) == ESP_OK) return true;
  // Clone boards often carry a sensor with no hardware JPEG (e.g. GC2145): grab raw RGB565
  // instead and encode to JPEG in software when sending.
  esp_camera_deinit();
  c.pixel_format = PIXFORMAT_RGB565;
  return esp_camera_init(&c) == ESP_OK;
}

// Sensor chip name for the boot line ("OV2640", "GC2145", ...) so we know what's fitted.
const char *cameraModel() {
  sensor_t *s = esp_camera_sensor_get();
  camera_sensor_info_t *info = s ? esp_camera_sensor_get_info(&s->id) : nullptr;
  return info ? info->name : "unknown";
}

void setup() {
  Serial.begin(115200);
  delay(200);

  camOk = initCamera();               // camera uses its own I2C port, so init it before Wire
  Wire.begin(I2C_SDA, I2C_SCL);
  amgOk = amg.begin(0x69, &Wire) || amg.begin(0x68, &Wire); // address depends on breakout's AD0
  adsOk = ads.begin(0x48, &Wire);
  if (adsOk) ads.setGain(GAIN_ONE);   // +/-4.096 V range: GSR output is 0-3.3 V
  probe.begin();
  probeOk = probe.getDeviceCount() > 0;

  if (ENABLE_WIFI) {
    WiFi.mode(WIFI_STA);
    WiFi.setAutoReconnect(true);      // keeps retrying in the background if the hotspot drops
    WiFi.begin(WIFI_SSID, WIFI_PASS);
    for (int i = 0; i < 20 && WiFi.status() != WL_CONNECTED; i++) delay(500); // wait max 10 s
    if (WiFi.status() == WL_CONNECTED) startWebServer();
  }

  Serial.printf("{\"type\":\"boot\",\"camera\":%s,\"camera_model\":\"%s\",\"amg8833\":%s,\"ads1115\":%s,\"ds18b20\":%s,\"psram\":%s}\n",
                camOk ? "true" : "false", cameraModel(), amgOk ? "true" : "false", adsOk ? "true" : "false",
                probeOk ? "true" : "false", psramFound() ? "true" : "false");
  printWifi();
}

void printWifi() {
  bool up = WiFi.status() == WL_CONNECTED;
  Serial.printf("{\"type\":\"wifi\",\"enabled\":%s,\"connected\":%s,\"ssid\":\"%s\",\"ip\":\"%s\",\"rssi\":%d}\n",
                ENABLE_WIFI ? "true" : "false", up ? "true" : "false", WIFI_SSID,
                up ? WiFi.localIP().toString().c_str() : "", up ? WiFi.RSSI() : 0);
}

void printNum(Print &out, float v, int decimals) {
  if (isnan(v)) out.print("null");
  else out.print(v, decimals);
}

// JPEG bytes for a frame. Sensors without hardware JPEG (our GC2145) get encoded here.
// Release with freeJpeg(). Returns nullptr if encoding fails.
uint8_t *frameJpeg(camera_fb_t *fb, size_t *len) {
  if (fb->format == PIXFORMAT_JPEG) { *len = fb->len; return fb->buf; }
  uint8_t *jpg = nullptr;
  return frame2jpg(fb, 80, &jpg, len) ? jpg : nullptr;  // quality 0-100
}

void freeJpeg(camera_fb_t *fb, uint8_t *jpg) {
  if (jpg && jpg != fb->buf) free(jpg);
}

// One JSON reading line to `out` (Serial, or a String for the web page).
void sendReading(bool withImage, Print &out) {
  // Grab the photo first so the sensor values sit closest in time to it.
  camera_fb_t *fb = nullptr;
  if (withImage) {
    fb = camOk ? esp_camera_fb_get() : nullptr;
    if (!fb) { out.println("{\"type\":\"error\",\"msg\":\"camera capture failed\"}"); return; }
  }

  float pixels[AMG88xx_PIXEL_ARRAY_SIZE];
  if (amgOk) amg.readPixels(pixels);

  float probeC = NAN;
  if (probeOk) {
    probe.requestTemperatures();      // blocks ~750 ms at 12-bit resolution
    float t = probe.getTempCByIndex(0);
    if (t != DEVICE_DISCONNECTED_C) probeC = t;
  }

  int16_t gsrRaw = adsOk ? ads.readADC_SingleEnded(GSR_CHANNEL) : 0;

  out.printf("{\"type\":\"reading\",\"ms\":%lu,\"thermal\":", millis());
  if (amgOk) {
    out.print('[');
    for (int i = 0; i < AMG88xx_PIXEL_ARRAY_SIZE; i++) {  // row-major, 8 rows x 8 cols, deg C
      if (i) out.print(',');
      out.print(pixels[i], 2);
    }
    out.print(']');
  } else {
    out.print("null");
  }
  out.print(",\"probe_c\":");
  printNum(out, probeC, 2);
  out.print(",\"gsr_raw\":");
  if (adsOk) out.print(gsrRaw); else out.print("null");
  out.print(",\"gsr_v\":");
  printNum(out, adsOk ? ads.computeVolts(gsrRaw) : NAN, 4);

  if (fb) {
    size_t jpgLen;
    uint8_t *jpg = frameJpeg(fb, &jpgLen);
    out.printf(",\"img_w\":%u,\"img_h\":%u,\"image_jpeg_b64\":", fb->width, fb->height);
    if (jpg) {
      out.print('"');
      out.print(base64::encode(jpg, jpgLen));
      out.print('"');
    } else {
      out.print("null");
    }
    freeJpeg(fb, jpg);
    esp_camera_fb_return(fb);
  }
  out.println('}');
}

// ---- Web page: open http://<ip from the wifi line> on a device joined to the same hotspot ----
const char PAGE[] PROGMEM = R"HTML(<!doctype html><html><head>
<meta name=viewport content="width=device-width,initial-scale=1"><title>Skin scanner</title>
<style>body{font-family:sans-serif;margin:16px;background:#111;color:#eee}
.row{display:flex;flex-wrap:wrap;gap:16px}img,canvas{width:320px;max-width:100%;border:1px solid #444}</style>
</head><body><h3>Skin scanner</h3>
<div class=row><img id=photo alt="camera"><canvas id=heat width=320 height=320></canvas></div>
<p id=info>loading...</p><label><input type=checkbox id=live checked> live</label>
<script>
const f=(v,d)=>v==null?'-':v.toFixed(d);
async function tick(){
  if(live.checked){try{
    const d=await (await fetch('/data')).json();
    info.textContent=draw(d.thermal)+'  |  probe '+f(d.probe_c,2)+' °C  |  GSR '+f(d.gsr_v,3)+' V';
    await new Promise(r=>{photo.onload=photo.onerror=r;photo.src='/capture.jpg?'+Date.now()});
  }catch(e){info.textContent='no connection: '+e}}
  setTimeout(tick,500);
}
function draw(t){ // colours are relative to this frame's min..max
  const c=heat.getContext('2d'),s=40;c.clearRect(0,0,320,320);
  if(!t)return 'no thermal sensor';
  const lo=Math.min(...t),hi=Math.max(...t);
  t.forEach((v,i)=>{const x=i%8*s,y=Math.floor(i/8)*s,k=hi>lo?(v-lo)/(hi-lo):0;
    c.fillStyle='hsl('+(240-240*k)+',100%,50%)';c.fillRect(x,y,s,s);
    c.fillStyle='#000';c.font='11px sans-serif';c.fillText(v.toFixed(1),x+6,y+24)});
  return 'thermal '+lo.toFixed(1)+' - '+hi.toFixed(1)+' °C';
}
tick();
</script></body></html>)HTML";

void handlePhoto() {
  camera_fb_t *fb = camOk ? esp_camera_fb_get() : nullptr;
  size_t len;
  uint8_t *jpg = fb ? frameJpeg(fb, &len) : nullptr;
  if (!jpg) server.send(503, "text/plain", "camera capture failed");
  else {
    server.setContentLength(len);
    server.send(200, "image/jpeg", "");
    server.sendContent((const char *)jpg, len);
  }
  if (fb) { freeJpeg(fb, jpg); esp_camera_fb_return(fb); }
}

bool webServerRunning = false;

void startWebServer() {
  if (webServerRunning) return;
  server.on("/", [] { server.send_P(200, "text/html", PAGE); });
  server.on("/data", [] {                        // same JSON as serial 's'
    StreamString json;
    sendReading(false, json);
    server.send(200, "application/json", (const String &)json);
  });
  server.on("/capture.jpg", handlePhoto);
  server.begin();
  webServerRunning = true;
}

void loop() {
  if (ENABLE_WIFI) {
    if (WiFi.status() == WL_CONNECTED) {
      if (!webServerRunning) startWebServer();
      server.handleClient();
    } else {
      webServerRunning = false;
    }
  }
  if (!Serial.available()) return;
  char cmd = Serial.read();
  if (cmd == 's') sendReading(false, Serial);
  else if (cmd == 'c') sendReading(true, Serial);
  else if (cmd == 'w') printWifi();
  // anything else (newlines etc.) is ignored
}
