#include <Arduino.h>

// =================== CẤU HÌNH PHẦN CỨNG ===================
// out2 trên sơ đồ nối trực tiếp vào GPIO3 của ESP32-C3 Super Mini
#define GEIGER_PIN        3        
#define INTERRUPT_MODE    RISING   // Xung kích từ IC 555 (LOW lên HIGH)

// =================== THÔNG SỐ VÀ HIỆU CHUẨN ===================
#define DEBOUNCE_TIME_US  600      // Chống dội xung nhiễu (microsecond)

// Hệ số chuyển đổi CPM sang uSv/h (cho ống J305 / M4011)
const float CONV_FACTOR = 0.00812; 

// =================== BIẾN TOÀN CỤC ===================
volatile unsigned long totalPulseCount = 0;
volatile unsigned long lastPulseMicros = 0;

// Cửa sổ trượt 60 giây để tính CPM liên tục
const int WINDOW_SIZE = 60;
uint16_t pulseHistory[WINDOW_SIZE] = {0};
int historyIndex = 0;
unsigned long lastSecondTick = 0;

// Hàm ngắt xử lý xung đặt trong IRAM
void IRAM_ATTR geigerISR() {
  unsigned long now = micros();
  if (now - lastPulseMicros >= DEBOUNCE_TIME_US) {
    totalPulseCount++;
    lastPulseMicros = now;
  }
}

void setup() {
  Serial.begin(115200);
  delay(1500); 

  Serial.println("\n--- ESP32-C3 Super Mini Geiger Counter (VS Code) ---");

  pinMode(GEIGER_PIN, INPUT);
  attachInterrupt(digitalPinToInterrupt(GEIGER_PIN), geigerISR, INTERRUPT_MODE);

  lastSecondTick = millis();
}

void loop() {
  unsigned long currentMillis = millis();

  // Cập nhật tính toán định kỳ mỗi 1 giây
  if (currentMillis - lastSecondTick >= 1000) {
    lastSecondTick += 1000;

    noInterrupts();
    static unsigned long lastTotalPulse = 0;
    unsigned long currentTotal = totalPulseCount;
    interrupts();

    unsigned int pulsesInLastSec = currentTotal - lastTotalPulse;
    lastTotalPulse = currentTotal;

    pulseHistory[historyIndex] = pulsesInLastSec;
    historyIndex = (historyIndex + 1) % WINDOW_SIZE;

    unsigned long cpm = 0;
    for (int i = 0; i < WINDOW_SIZE; i++) {
      cpm += pulseHistory[i];
    }

    float uSvh = cpm * CONV_FACTOR;

    Serial.printf("[CPS: %2u]  |  [CPM: %3lu]  |  [Dose: %6.4f uSv/h]  |  [Tong: %lu]\n", 
                  pulsesInLastSec, cpm, uSvh, currentTotal);
  }
}