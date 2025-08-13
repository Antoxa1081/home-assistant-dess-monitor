import socket
import time

ELFIN_IP = '10.0.0.97'
ELFIN_PORT = 8899
command = b'QPIGS\r'

def send_command():
    try:
        print(f"Подключение к {ELFIN_IP}:{ELFIN_PORT}")
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.settimeout(5)
            s.connect((ELFIN_IP, ELFIN_PORT))
            print("✅ Соединено. Отправка команды QPIGS...")
            s.sendall(command)
            time.sleep(2)  # ждём, пока инвертор ответит

            response = b''
            while True:
                try:
                    part = s.recv(1024)
                    if not part:
                        break
                    response += part
                except socket.timeout:
                    break

            print("\n🔁 Ответ (сырые байты):", repr(response))
            print("📦 Ответ (текст):", response.decode(errors='ignore'))

    except socket.timeout:
        print("⛔ Таймаут — Elfin не ответил.")
    except Exception as e:
        print("⛔ Ошибка:", e)

if __name__ == "__main__":
    send_command()
