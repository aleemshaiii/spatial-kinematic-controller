"""Optional OpenCV HUD; no UI calls on the capture thread."""
import cv2


def show(frame, hand, metrics, state):
    image = frame.copy()
    if hand is not None:
        h, w = image.shape[:2]
        for x, y, _ in hand.normalized:
            cv2.circle(image, (round(x * w), round(y * h)), 2, (0, 240, 0), -1)
    lines = [f"FPS {metrics['fps']:.1f} | read->submit {metrics['latency_ms']:.1f} ms",
             f"steer {state.roll:+.2f}  trigger {state.throttle:.2f}  A {state.buttons & 1}",
             "Q / Esc: quit | C: calibrate neutral roll"]
    if "keyboard" in metrics:
        kb = metrics["keyboard"]
        lines.append(f"Game focused: {kb['focused']} | GAS: {kb['accelerator']} | BRAKE: {kb['brake']}")
    for i, line in enumerate(lines):
        cv2.putText(image, line, (10, 24 + 24 * i), cv2.FONT_HERSHEY_SIMPLEX,
                    0.5, (0, 255, 255), 1, cv2.LINE_AA)
    cv2.imshow("Spatial Kinematic Controller", image)
    return cv2.waitKey(1) & 0xFF


def close():
    cv2.destroyAllWindows()
