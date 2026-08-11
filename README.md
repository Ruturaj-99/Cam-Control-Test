# VDMS Camera Test (Proof of Concept)

A minimal desktop app that proves one thing only:

> A physical USB camera connected to a Windows 10/11 PC can be opened,
> previewed, and captured **programmatically** by our own application, and the
> frame saved locally as a JPG.

This is **not** the VDMS application. There is no AWS, no OCR, no database,
no login — by design.

## Requirements

- Windows 10/11
- Python 3.10+ (tested with 3.13)
- A physical USB (UVC) camera

## Setup

```powershell
pip install -r requirements.txt
```

## Run

```powershell
python camera_test.py
```

## How it works

- Camera devices are enumerated by name using DirectShow (`pygrabber`).
- The selected camera is opened with OpenCV using the Windows Media
  Foundation backend, requesting the highest resolution the camera supports.
- A background thread continuously reads full-resolution frames; the UI shows
  a scaled-down live preview.
- Clicking **CAPTURE** takes the most recent full-resolution frame and saves
  it as `captures/card_YYYYMMDD_HHMMSS.jpg` (JPEG quality 95, no resizing).
- The saved image and its actual resolution are shown in the window.

## Test plan

1. **Connect USB camera** to the PC. If Teams/Zoom/the Windows Camera app is
   using it, close them first.
2. **Launch the app**: `python camera_test.py`
3. **Verify the camera appears** in the "Camera" dropdown by its real device
   name. If you plugged it in after launching, click **Refresh**.
4. **Select the camera** from the dropdown.
5. **Verify the live preview** starts and the "Preview resolution" line shows
   the negotiated resolution.
6. **Place a real visiting card** in front of the camera, in focus, well lit.
7. **Click CAPTURE.**
8. **Verify the file was created** — the full path is shown under
   "Last Capture", inside the `captures/` folder next to `camera_test.py`.
9. **Open the saved JPG** in Windows Photos and confirm the card text is
   sharp and readable at 100% zoom.
10. **Repeat the capture at least 20 times** (different cards / positions).
11. **Check for failures** — every click must show "Capture successful" and
    produce a distinct file. Any red error message counts as a failure.

## Success criteria

The architecture is considered viable only if all of these hold:

1. Windows detects the physical USB camera.
2. The app lists and opens it.
3. Live preview runs smoothly.
4. CAPTURE saves a real frame every time.
5. 20+ repeated captures succeed without errors or app restarts.
6. Visiting-card text in the saved images is visually readable.

## Reconsider the architecture if

- The camera is detected by Windows but the app cannot open it.
- Captures intermittently fail or the preview freezes during long sessions.
- The maximum negotiated resolution is too low to read card text.

## Troubleshooting

- **"No camera detected"** — check the USB connection, try another port,
  then click Refresh.
- **"Could not open the camera"** — another app is probably using it
  (Teams, Zoom, Windows Camera). Close it and reselect the camera.
- **Camera opens but no frames** — check
  *Settings → Privacy & security → Camera → "Let desktop apps access your
  camera"* is ON.
