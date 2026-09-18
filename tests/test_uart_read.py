"""Test the actual UART reader with a fake serial response. Requires g++.

Run: python -B -m unittest discover -s tests -p test_uart_read.py
"""

from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]


def function(source, signature):
    start = source.index(signature)
    brace = source.index("{", start)
    depth = 1
    end = brace + 1
    while depth:
        depth += (source[end] == "{") - (source[end] == "}")
        end += 1
    return source[start:end]


class TestUartRead(unittest.TestCase):
    def test_actual_library_reader(self):
        # Compile the library's real read/CRC functions against a fake UART.
        # The original reader must fail this same regression.
        corrected = (ROOT / 'src/source/TMC2208Stepper.cpp').read_text(encoding='utf-8')
        original = corrected.replace("|| out == 0 )", "|| crc == 0 )")
        harness = r'''
#include <stdint.h>
#include <stdio.h>
#define TMC_READ 0
void delay(int) {}
class TMC2208Stepper {
 public:
  bool CRCerror = false;
  uint64_t reply = 0;
  static constexpr uint8_t TMC2208_SYNC = 5, slave_address = 0;
  static constexpr int max_retries = 2, replyDelay = 2, abort_window = 5;
  void preReadCommunication() {}
  void postReadCommunication() {}
  uint64_t _sendDatagram(uint8_t*, uint8_t, uint16_t) { return reply; }
  uint8_t calcCRC(uint8_t[], uint8_t);
  uint32_t read(uint8_t);
  void respond(uint8_t reg, uint32_t value) {
    uint8_t bytes[] = {5, 255, reg, uint8_t(value >> 24), uint8_t(value >> 16), uint8_t(value >> 8), uint8_t(value)};
    reply = 0;
    for (uint8_t b : bytes) reply = (reply << 8) | b;
    reply = (reply << 8) | calcCRC(bytes, 7);
  }
};
/* LIBRARY */
int main() {
  TMC2208Stepper driver;
  // Covers every counter value, including 174 (CRC zero) and wrap to zero.
  for (uint32_t i = 0; i <= 256; ++i) {
    driver.respond(2, i & 255);
    if (driver.read(2) != (i & 255) || driver.CRCerror) return 1;
  }
  driver.reply = 0;  // Timeout / no complete frame.
  if (driver.read(2) != 0 || !driver.CRCerror) return 2;
  driver.respond(2, 174);
  driver.reply ^= 1;  // Corrupt the checksum.
  if (driver.read(2) != 0 || !driver.CRCerror) return 3;
  driver.respond(0x6f, 0);  // A valid zero status value is not a timeout.
  if (driver.read(0x6f) != 0 || driver.CRCerror) return 4;
  driver.respond(0x6f, 0xc0070000);  // Exact status from the reported log.
  if (driver.read(0x6f) != 0xc0070000 || driver.CRCerror) return 5;
  return 0;
}
'''
        compiler = shutil.which("g++")
        self.assertIsNotNone(compiler, "g++ is required for the UART regression")
        with tempfile.TemporaryDirectory() as directory:
            directory = Path(directory)
            for source, expected in ((original, 1), (corrected, 0)):
                functions = function(source, "uint8_t TMC2208Stepper::calcCRC(") + "\n" + function(source, "uint32_t TMC2208Stepper::read(")
                cpp = directory / "uart.cpp"
                exe = directory / "uart.exe"
                cpp.write_text(harness.replace("/* LIBRARY */", functions), encoding="utf-8")
                subprocess.run([compiler, "-std=c++11", str(cpp), "-o", str(exe)], check=True)
                self.assertEqual(subprocess.run([str(exe)]).returncode, expected)


if __name__ == "__main__":
    unittest.main()
