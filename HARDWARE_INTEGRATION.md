# Main Gate Buzzer Integration Guide

## 1. Purpose

The application produces an `alert_generated` audit flag and an `Alert.audible` decision for `Blocked` and `Unauthorized` plates. These software signals are the control boundary for a physical Main Gate warning device. The current repository does not assume a specific GPIO board, relay module, or buzzer voltage.

Use a qualified technician for final installation. Do not connect a buzzer, relay coil, or gate-control circuit directly to a computer USB pin, Raspberry Pi GPIO pin, Arduino I/O pin, or network device output.

## 2. Recommended Architecture

```text
Flask application
      |
      | alert event: Blocked / Unauthorized
      v
Hardware adapter service
      |
      | isolated low-voltage control signal
      v
Opto-isolated relay or transistor driver
      |
      +--> 5 V or 12 V active buzzer
      +--> red warning lamp
      +--> optional operator acknowledge button
```

The buzzer should warn the security officer. It should not directly open, close, or override the gate unless a separate, reviewed access-control interlock is designed and approved.

## 3. Recommended Components

- A low-voltage active buzzer rated for the selected supply.
- A regulated power supply matching the buzzer rating.
- An opto-isolated relay module or a transistor/MOSFET driver with a flyback diode for inductive loads.
- A small hardware adapter such as a Raspberry Pi, Arduino-class controller, or industrial I/O module.
- A red warning indicator and an operator acknowledge button.
- A fused enclosure and labelled terminal blocks.
- UPS protection for the processing node, network switch, and controller.

Select the controller only after confirming the available installation environment. GPIO voltage and current limits vary by board.

## 4. Safe Wiring Pattern

For a DC buzzer driven by a transistor or MOSFET:

```text
DC supply +  ---- fuse ---- buzzer +
buzzer -      ---- driver output
DC supply -  ---------------- driver ground
controller output ----------- isolated driver input
controller ground ----------- driver signal ground (only where the module requires it)
```

For a relay module:

```text
DC supply +  ---- fuse ---- relay COM
relay NO      -------------- buzzer +
buzzer -      -------------- DC supply -
controller    -------------- opto-isolated relay input
```

Use `NO` (normally open) so the buzzer is silent when the controller is unpowered. For critical safety installations, have the site electrician review whether fail-silent or fail-alarm behavior is appropriate.

## 5. Electrical Rules

1. Confirm the buzzer voltage and current from its datasheet.
2. Use a separate regulated supply for the buzzer when its current exceeds the controller output rating.
3. Use isolation between computing equipment and field wiring where practical.
4. Add a flyback diode across a DC relay coil or other inductive load.
5. Add a fuse close to the field power supply.
6. Keep signal and power wiring labelled and physically protected.
7. Never use mains voltage on a breadboard or an exposed relay module.
8. Test with the gate mechanism disconnected.
9. Provide a manual acknowledge/silence control for the security booth.
10. Log every alert even if the buzzer is offline.

## 6. Software Adapter Contract

The application already exposes the decision needed by an adapter:

- `Allowed`: no audible alert.
- `Blocked`: audible alert required.
- `Unauthorized`: audible alert required.
- `Unreadable`: manual review warning; no automatic authorization.

A production adapter can consume this signal through one of these controlled interfaces:

- A local controller API over a private network.
- A serial connection to an industrial I/O controller.
- A message queue on the secured gate network.
- A GPIO service running separately from Flask.

Keep the hardware adapter separate from the Flask web process. If the adapter fails, the application must continue recording `alert_generated` and report the hardware fault to the operator.

## 7. Recommended Alert Sequence

1. Flask completes OCR and access classification.
2. The application writes the detection record to MySQL.
3. The alert adapter receives the status event.
4. For `Blocked` or `Unauthorized`, the adapter activates the buzzer and red lamp.
5. The buzzer sounds for a bounded interval, such as 3 to 5 seconds.
6. The operator acknowledges the alert.
7. The adapter returns an acknowledgement or fault state.
8. The event and hardware result remain available for audit.

Do not allow repeated OCR frames to trigger an unlimited alarm loop. Add a cooldown keyed by plate number and time window in the adapter.

## 8. Commissioning Checklist

- Confirm the buzzer supply voltage and current.
- Confirm controller output limits.
- Verify relay isolation and fuse protection.
- Test the buzzer with the Flask application stopped.
- Test a simulated `Blocked` event without a vehicle at the gate.
- Verify the alert does not open or close the gate.
- Disconnect the controller and confirm audit records are still created.
- Test power restoration and UPS behavior.
- Test operator acknowledgement.
- Record wiring diagrams, device addresses, firmware versions, and maintenance contacts.

## 9. Security and Operations

Restrict the hardware controller to the private gate network. Use authenticated communication where supported. Do not expose GPIO, serial bridges, or controller APIs to the public internet. Store controller credentials outside the repository and rotate them according to Academy policy.

The buzzer is an operator-warning device, not the sole access-control authority. The security officer remains responsible for final verification when the plate is unreadable, partially obscured, or below the configured confidence threshold.
