"""
Water Meter Reader - Entry Point
Run this file to start the application.
"""

import sys
import os

# Add src folder to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "src"))

from meter_reader import MeterReaderApp

if __name__ == "__main__":
    app = MeterReaderApp()
    app.mainloop()
