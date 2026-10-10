# Full Stack Architecture

### Hardware: ESP32 + Gyrosensor 
### Local HDMI Display Device
### API for Game Logic: FastAPI Backend
### Frontend: HTML + JS (Three.js)

```text
 +------------------------+             +----------------------------------+
 |  ESP32 Controller      |             |  Frontend Display                |
 |  (Gyroscope / MPU6050) |             |  (HTML + JS / Three.js)          |
 +-----------+------------+             +----------------+-----------------+
             |                                           |
             | 1. High-Frequency Motion Data            | 2. Game Lifecycle
             |    (UDP / WebSockets - Local Network)     |    (REST HTTP)
             v                                           v
 +-----------+-------------------------------------------+-----------------+
 |                                                                         |
 |                      Local HDMI Display Device                          |
 |            (Mini-PC / Laptop / Raspberry Pi output to TV)              |
 |                                                                         |
 +-------------------------------------+-----------------------------------+
                                       |
                                       | 3. High-Score & Stats Persistence
                                       |    (Async REST APIs)
                                       v
                        +--------------+---------------+
                        |  FastAPI Backend             |
                        |  (Session, Leaderboards, DB) |
                        +------------------------------+
```