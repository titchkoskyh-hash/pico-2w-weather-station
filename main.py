import network
import socket
import time
import onewire
import ds18x20
import bme280
import json
import math
from machine import Pin, I2C

# Wi-Fi & Weather Underground Configuration
WIFI_SSID = 'YOUR_WIFI_SSID'
WIFI_PASSWORD = 'YOUR_WIFI_PASSWORD'
WU_STATION_ID = 'YOUR_STATION_ID'
WU_STATION_KEY = 'YOUR_STATION_KEY'
WU_UPLOAD_INTERVAL_MS = 5 * 60 * 1000  # 5 minutes
WU_HOST = "weatherstation.wunderground.com"

ELEVATION_M = 1045  # your station's elevation above sea level, in metres (Calgary is roughly 1045 m)

SENSOR_INTERVAL_MS = 3000
DS_CONVERT_MS = 800  # DS18B20 needs ~750 ms for a 12-bit conversion

# Hardware Initialization
ds_pin = Pin(16)
ds_sensor = ds18x20.DS18X20(onewire.OneWire(ds_pin))

i2c = I2C(0, sda=Pin(0), scl=Pin(1), freq=400000)
devices = i2c.scan()
bme_addr = 0x76 if 0x76 in devices else 0x77
bme = bme280.BME280(i2c=i2c, addr=bme_addr)

print("Scanning for DS18B20 sensor...")
roms = ds_sensor.scan()
print(f"Found {len(roms)} DS18B20 sensor(s).")

led = Pin('LED', Pin.OUT)
wlan = network.WLAN(network.STA_IF)


def reset_wifi():
    """Power-cycles the Wi-Fi chip. Fixes CYW43 'core not in reset' / EPERM errors."""
    try:
        wlan.active(False)
        time.sleep(1)
        wlan.active(True)
        time.sleep(2)
    except Exception as e:
        print("Wi-Fi reset failed:", e)


reset_wifi()

# Global data cache
cached_data = {"ds_temp": None, "humidity": 0.0, "pressure": 0.0}
last_sensor_read = None
ds_converting = False
ds_convert_start = 0


def build_html():
    """Builds the HTML page structure."""
    html_lines = [
        "HTTP/1.1 200 OK\r\nContent-Type: text/html\r\nConnection: close\r\n\r\n",
        "<!DOCTYPE html><html><head><title>Weather Monitor</title><style>",
        "body { font-family: sans-serif; text-align: center; padding-top: 50px; background-color: #f4f4f9; color: #333; }",
        ".card { background: white; max-width: 380px; margin: 30px auto; padding: 25px; border-radius: 12px; box-shadow: 0 4px 10px rgba(0,0,0,0.1); }",
        ".value { font-size: 42px; font-weight: bold; color: #007bff; margin: 15px 0; }",
        ".sub-value { font-size: 20px; font-weight: bold; color: #28a745; margin: 5px 0; }",
        ".grid { display: flex; justify-content: space-around; margin-top: 20px; border-top: 1px solid #eee; padding-top: 15px; }",
        ".grid-item { font-size: 14px; color: #555; }",
        ".indicator { width: 10px; height: 10px; background-color: #28a745; border-radius: 50%; display: inline-block; margin-right: 5px; }",
        "</style></head><body><h1>Pico 2 W Dashboard</h1><div class=\"card\">",
        "  <h3>DS18B20 Temperature</h3><div class=\"value\" id=\"avg-val\">-- &deg;C</div>",
        "  <div class=\"grid\"><div class=\"grid-item\"><strong>Humidity</strong><div id=\"hum-val\" class=\"sub-value\">--</div></div>",
        "  <div class=\"grid-item\"><strong>Pressure (SL)</strong><div id=\"pres-val\" class=\"sub-value\" style=\"color:#17a2b8;\">--</div></div>",
        "  <div class=\"grid-item\"><strong>Dew Point</strong><div id=\"dew-val\" class=\"sub-value\" style=\"color:#fd7e14;\">--</div></div></div>",
        "  <p style=\"color: gray; font-size: 12px; margin-top: 20px;\"><span class=\"indicator\"></span>Live data polling active</p></div>",
        "<script>async function updateData() { try { let r = await fetch('/data'); let d = await r.json();",
        "if (!d.error) { document.getElementById('avg-val').innerHTML = d.ds_temp + (d.ds_temp !== 'No Sensor' ? ' &deg;C' : '');",
        "document.getElementById('hum-val').innerText = d.humidity; document.getElementById('pres-val').innerText = d.pressure; document.getElementById('dew-val').innerHTML = d.dewpoint; }",
        "} catch(e) {} } setInterval(updateData, 2000); updateData();</script></body></html>"
    ]
    return "\n".join(html_lines)


def connect_wifi():
    if wlan.isconnected():
        return wlan.ifconfig()[0]
    print(f"Connecting to: {WIFI_SSID}...")
    try:
        wlan.connect(WIFI_SSID, WIFI_PASSWORD)
    except OSError as e:
        print("Wi-Fi connect error:", e, "- resetting Wi-Fi chip")
        reset_wifi()
        return None
    timeout = 10
    while not wlan.isconnected() and timeout > 0:
        led.toggle()
        time.sleep(1)
        timeout -= 1
    if wlan.isconnected():
        led.on()
        ip = wlan.ifconfig()[0]
        print(f"Connected! IP Address: {ip}")
        return ip
    led.off()
    return None


def update_sensor_cache():
    """Non-blocking sensor refresh: starts a DS18B20 conversion, then collects
    the result on a later call instead of sleeping."""
    global last_sensor_read, ds_converting, ds_convert_start
    now = time.ticks_ms()

    # Collect a finished DS18B20 conversion
    if ds_converting and time.ticks_diff(now, ds_convert_start) >= DS_CONVERT_MS:
        try:
            cached_data["ds_temp"] = ds_sensor.read_temp(roms[0])
        except Exception as e:
            print("DS18B20 Read Fail:", e)
            cached_data["ds_temp"] = None
        ds_converting = False

    # Start a new cycle
    if last_sensor_read is None or time.ticks_diff(now, last_sensor_read) >= SENSOR_INTERVAL_MS:
        try:
            t, p, h = bme.read_compensated_data()
            cached_data["humidity"] = float(h)
            cached_data["pressure"] = float(p / 100.0)
        except Exception as e:
            print("BME Read Fail:", e)

        if roms and not ds_converting:
            try:
                ds_sensor.convert_temp()
                ds_converting = True
                ds_convert_start = now
            except Exception as e:
                print("DS18B20 Convert Fail:", e)

        last_sensor_read = now


def sea_level_hpa(station_hpa, temp_c):
    """Converts station pressure to sea-level pressure (what weather reports and WU expect)."""
    if temp_c is None:
        temp_c = 15.0
    return station_hpa * (1 - (0.0065 * ELEVATION_M) / (temp_c + 0.0065 * ELEVATION_M + 273.15)) ** -5.257


def dewpoint_c(temp_c, rh):
    """Dewpoint in Celsius using the Magnus formula."""
    if rh <= 0:
        return None
    b, c = 17.62, 243.12
    gamma = math.log(rh / 100.0) + (b * temp_c) / (c + temp_c)
    return (c * gamma) / (b - gamma)


def get_sensor_json():
    """Returns data straight from the cache."""
    update_sensor_cache()
    ds_str = f"{cached_data['ds_temp']:.1f}" if cached_data['ds_temp'] is not None else "No Sensor"
    if cached_data['ds_temp'] is not None:
        dew = dewpoint_c(cached_data['ds_temp'], cached_data['humidity'])
        dew_str = f"{dew:.1f} &deg;C" if dew is not None else "--"
    else:
        dew_str = "--"
    return json.dumps({
        "ds_temp": ds_str,
        "dewpoint": dew_str,
        "humidity": f"{cached_data['humidity']:.1f}%",
        "pressure": f"{sea_level_hpa(cached_data['pressure'], cached_data['ds_temp']):.1f} hPa"
    })


def send_to_wunderground():
    """Uploads metrics to Weather Underground over raw HTTP using imperial units."""
    if cached_data['ds_temp'] is None:
        print("Skipped WU upload - waiting for valid DS18B20 temperature.")
        return

    temp_f = cached_data['ds_temp'] * 9 / 5 + 32
    pressure_in = sea_level_hpa(cached_data['pressure'], cached_data['ds_temp']) * 0.02953
    dew_c = dewpoint_c(cached_data['ds_temp'], cached_data['humidity'])
    dew_f = dew_c * 9 / 5 + 32 if dew_c is not None else None

    query = (
        "ID={id}&PASSWORD={key}&dateutc=now&tempf={tempf:.1f}"
        "&baromin={baromin:.2f}&humidity={humidity:.0f}"
        "&action=updateraw&softwaretype=pico2w-custom"
    ).format(id=WU_STATION_ID, key=WU_STATION_KEY, tempf=temp_f,
             baromin=pressure_in, humidity=cached_data['humidity'])

    if dew_f is not None:
        query += "&dewptf={:.1f}".format(dew_f)

    print("WU query:", query.replace(WU_STATION_KEY, "***"))

    request = (
        "GET /weatherstation/updateweatherstation.php?{query} HTTP/1.1\r\n"
        "Host: {host}\r\n"
        "Connection: close\r\n"
        "\r\n"
    ).format(query=query, host=WU_HOST)

    s = None
    try:
        addr = socket.getaddrinfo(WU_HOST, 80)[0][-1]
        s = socket.socket()
        s.settimeout(8)
        s.connect(addr)
        s.send(request.encode())

        response = b""
        while True:
            chunk = s.recv(200)
            if not chunk:
                break
            response += chunk
        print("WU Response:", response.decode().split("\r\n"))
    except Exception as e:
        print("WU Upload Failed:", e)
    finally:
        if s:
            s.close()


def start_server():
    ip = connect_wifi()
    if not ip:
        return False

    s_sock = socket.socket()
    s_sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    try:
        s_sock.bind((ip, 80))
        s_sock.listen(1)
        s_sock.settimeout(0.1)
        print(f"Web server running at http://{ip}")
    except Exception as e:
        print("Socket bind failed:", e)
        s_sock.close()
        return False

    last_wu_upload = time.ticks_add(time.ticks_ms(), -WU_UPLOAD_INTERVAL_MS)

    while True:
        if not wlan.isconnected():
            print("Wi-Fi connection dropped! Tearing down server socket for restart...")
            s_sock.close()
            return False

        update_sensor_cache()

        if time.ticks_diff(time.ticks_ms(), last_wu_upload) >= WU_UPLOAD_INTERVAL_MS:
            # Only upload once we have a valid temperature; otherwise retry next loop
            if cached_data['ds_temp'] is not None:
                print("Uploading data to Weather Underground...")
                send_to_wunderground()
                last_wu_upload = time.ticks_ms()

        c_sock = None
        try:
            c_sock, _ = s_sock.accept()
            c_sock.settimeout(2.0)
            req = c_sock.recv(1024).decode('utf-8', 'ignore')

            if "GET /data " in req:
                c_sock.send(f"HTTP/1.1 200 OK\r\nContent-Type: application/json\r\nConnection: close\r\n\r\n{get_sensor_json()}".encode())
            else:
                c_sock.send(build_html().encode())
        except OSError:
            pass
        except Exception as e:
            print("Server exception:", e)
        finally:
            if c_sock:
                try:
                    c_sock.close()
                except Exception:
                    pass


# Main loop wrapper
while True:
    if not start_server():
        led.off()
        print("Server dropped out or could not bind. Retrying in 5 seconds...")
        time.sleep(5)
        reset_wifi()
