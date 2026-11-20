#include <Arduino.h>

// Chân kết nối theo sơ đồ mạch U5 (ESP32-C3 SuperMini)
constexpr uint8_t PIN_OUT1 = 0; // GPIO0: Xung thô trực tiếp từ T2 (Active-Low -> FALLING)
constexpr uint8_t PIN_OUT2 = 3; // GPIO3: Xung chuẩn hóa qua IC 555 (Active-High -> RISING)

// Biến đếm trong ngắt (ISR)
volatile uint32_t totalPulsesOut1 = 0;
volatile uint32_t totalPulsesOut2 = 0;
volatile bool newPulseFlag = false;

portMUX_TYPE timerMux = portMUX_INITIALIZER_UNLOCKED;
uint32_t lastTickMs = 0;

// Ngắt đọc xung thô (out1 - sườn xuống)
void IRAM_ATTR onPulseOut1() {
    portENTER_CRITICAL_ISR(&timerMux);
    totalPulsesOut1++;
    newPulseFlag = true;
    portEXIT_CRITICAL_ISR(&timerMux);
}

// Ngắt đọc xung đã định dạng qua NE555 (out2 - sườn lên)
void IRAM_ATTR onPulseOut2() {
    portENTER_CRITICAL_ISR(&timerMux);
    totalPulsesOut2++;
    newPulseFlag = true;
    portEXIT_CRITICAL_ISR(&timerMux);
}

void setup() {
    Serial.begin(115200);
    delay(1500); // Chờ ổn định cổng USB CDC trên ESP32-C3

    // GPIO0 đã có R8 (47k) + R9 (470k) kéo lên nguồn; GPIO3 nhận mức logic trực tiếp từ pin 3 NE555
    pinMode(PIN_OUT1, INPUT);
    pinMode(PIN_OUT2, INPUT);

    attachInterrupt(digitalPinToInterrupt(PIN_OUT1), onPulseOut1, FALLING);
    attachInterrupt(digitalPinToInterrupt(PIN_OUT2), onPulseOut2, RISING);

    Serial.println("HEADER,TYPE,ESP_MS,TOTAL_OUT1,TOTAL_OUT2");
    lastTickMs = millis();
}

void loop() {
    uint32_t nowMs = millis();
    uint32_t c1, c2;
    bool hasPulse = false;

    // Đọc an toàn biến chia sẻ với ISR
    portENTER_CRITICAL(&timerMux);
    c1 = totalPulsesOut1;
    c2 = totalPulsesOut2;
    if (newPulseFlag) {
        hasPulse = true;
        newPulseFlag = false;
    }
    portEXIT_CRITICAL(&timerMux);

    // 1. Gửi sự kiện ngay khi có xung (dùng kiểm tra khoảng cách giữa 2 xung / nhiễu dội cho TN1)
    if (hasPulse) {
        Serial.printf("PULSE,%lu,%lu,%lu\n", nowMs, c1, c2);
    }

    // 2. Gửi gói nhịp chuẩn mỗi 1000 ms (dùng tính CPM, chia cửa sổ 10s/30s/60s/300s & kiểm tra mất mẫu TN8)
    if (nowMs - lastTickMs >= 1000) {
        lastTickMs += 1000;
        Serial.printf("TICK,%lu,%lu,%lu\n", nowMs, c1, c2);
    }
}