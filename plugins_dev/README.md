```import subprocess
import sys
import os

python_exe = os.path.join(sys.prefix, 'python.exe')

print(f"Используем Python по пути: {python_exe}")
print("Начинаю скачивание библиотек, интерфейс QGIS может временно зависнуть...")

subprocess.check_call([
    python_exe, "-m", "pip", "install", 
    "ultralytics", "transformers", "opencv-python-headless"
])

print("Установка успешно завершена! Можно перезапускать QGIS.")
```