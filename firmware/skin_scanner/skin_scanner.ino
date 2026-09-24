// Thermal + visible-light skin scanner — ESP32-CAM (AI-Thinker) firmware v0.1
//
// Serial commands (115200 baud, type in Serial Monitor or send from Python):
//   s  -> sensor reading (thermal 8x8 + probe temp + GSR) as one JSON line
//   c  -> same as 's' plus a JPEG photo (base64) in the same JSON line
//   w  -> WiFi status (connected, IP, signal strength)
// Every message is one line of JSON starting with '{'. Ignore any other lines
// (the ESP32 boot ROM prints garbage/text at startup).
//
// Libraries (Arduino Library Manager):
//   Adafruit AMG88xx, Adafruit ADS1X15, OneWire, DallasTemperature
// Board: "AI Thinker ESP32-CAM" (esp32 core by Espressif).

#include "esp_camera.h"
#include <Wire.h>
#include <WiFi.h>
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
#if __has_include("secrets.h")  // WiFi credentials live in git-ignored secrets.h
#include "secrets.h"
#else
#define WIFI_SSID    ""               // no secrets.h: WiFi just stays disconnected
#define WIFI_PASS    ""
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
  return esp_camera_init(&c) == ESP_OK;
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
  }

  Serial.printf("{\"type\":\"boot\",\"camera\":%s,\"amg8833\":%s,\"ads1115\":%s,\"ds18b20\":%s,\"psram\":%s}\n",
                camOk ? "true" : "false", amgOk ? "true" : "false", adsOk ? "true" : "false",
                probeOk ? "true" : "false", psramFound() ? "true" : "false");
  printWifi();
}

void printWifi() {
  bool up = WiFi.status() == WL_CONNECTED;
  Serial.printf("{\"type\":\"wifi\",\"enabled\":%s,\"connected\":%s,\"ssid\":\"%s\",\"ip\":\"%s\",\"rssi\":%d}\n",
                ENABLE_WIFI ? "true" : "false", up ? "true" : "false", WIFI_SSID,
                up ? WiFi.localIP().toString().c_str() : "", up ? WiFi.RSSI() : 0);
}

void printNum(float v, int decimals) {
  if (isnan(v)) Serial.print("null");
  else Serial.print(v, decimals);
}

void sendReading(bool withImage) {
  // Grab the photo first so the sensor values sit closest in time to it.
  camera_fb_t *fb = nullptr;
  if (withImage) {
    fb = camOk ? esp_camera_fb_get() : nullptr;
    if (!fb) { Serial.println("{\"type\":\"error\",\"msg\":\"camera capture failed\"}"); return; }
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

  Serial.printf("{\"type\":\"reading\",\"ms\":%lu,\"thermal\":", millis());
  if (amgOk) {
    Serial.print('[');
    for (int i = 0; i < AMG88xx_PIXEL_ARRAY_SIZE; i++) {  // row-major, 8 rows x 8 cols, deg C
      if (i) Serial.print(',');
      Serial.print(pixels[i], 2);
    }
    Serial.print(']');
  } else {
    Serial.print("null");
  }
  Serial.print(",\"probe_c\":");
  printNum(probeC, 2);
  Serial.print(",\"gsr_raw\":");
  if (adsOk) Serial.print(gsrRaw); else Serial.print("null");
  Serial.print(",\"gsr_v\":");
  printNum(adsOk ? ads.computeVolts(gsrRaw) : NAN, 4);

  if (fb) {
    Serial.printf(",\"img_w\":%u,\"img_h\":%u,\"image_jpeg_b64\":\"", fb->width, fb->height);
    Serial.print(base64::encode(fb->buf, fb->len));
    Serial.print('"');
    esp_camera_fb_return(fb);
  }
  Serial.println('}');
}

void loop() {
  if (!Serial.available()) return;
  char cmd = Serial.read();
  if (cmd == 's') sendReading(false);
  else if (cmd == 'c') sendReading(true);
  else if (cmd == 'w') printWifi();
  // anything else (newlines etc.) is ignored
}
