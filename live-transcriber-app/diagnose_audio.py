"""
Audio capture diagnostic. Shows which devices the transcriber will use and
whether they are actually receiving sound. Run this WHILE on your call.
"""
import time
import numpy as np
import soundcard as sc

SR = 16000


def meter(device, tag, seconds=5):
    print(f"\n[{tag}] recording {seconds}s -- make sure sound is happening now...")
    peak = 0.0
    with device.recorder(samplerate=SR, channels=1) as rec:
        for i in range(seconds):
            d = rec.record(numframes=SR)
            mono = d.mean(axis=1) if d.ndim > 1 else d
            rms = float(np.sqrt(np.mean(mono ** 2))) if mono.size else 0.0
            peak = max(peak, rms)
            bar = "#" * min(50, int(rms * 3000))
            print(f"   {tag} s{i+1}: level={rms:.4f} {bar}")
    verdict = "GOOD - signal detected" if peak > 0.004 else "SILENT - nothing captured!"
    print(f"   -> {tag}: {verdict} (peak {peak:.4f})")
    return peak


def main():
    spk = sc.default_speaker()
    mic = sc.default_microphone()
    print("=" * 60)
    print("DEFAULT OUTPUT (the 'Them' channel captures this):")
    print("   ", spk.name)
    print("DEFAULT MICROPHONE (the 'Me' channel captures this):")
    print("   ", mic.name)
    print("=" * 60)
    print("\nAll capture/loopback devices Windows exposes:")
    for m in sc.all_microphones(include_loopback=True):
        kind = "[LOOPBACK/output]" if m.isloopback else "[microphone]    "
        print(f"   {kind} {m.name}")

    loop = sc.get_microphone(id=str(spk.name), include_loopback=True)

    print("\n\n>>> TEST 1: THEM channel (your call audio).")
    print(">>> Make sure someone on the call is TALKING for the next 5 seconds.")
    input(">>> Press Enter when they're about to talk...")
    them_peak = meter(loop, "THEM")

    print("\n\n>>> TEST 2: ME channel (your microphone).")
    input(">>> Press Enter, then SPEAK for 5 seconds...")
    me_peak = meter(mic, "ME")

    print("\n" + "=" * 60)
    print("SUMMARY")
    print(f"  THEM (call audio): {'OK' if them_peak > 0.004 else 'NOT CAPTURED'}")
    print(f"  ME   (your mic)  : {'OK' if me_peak > 0.004 else 'NOT CAPTURED'}")
    if them_peak <= 0.004:
        print("\n  THEM is silent. The call audio is NOT going to the default")
        print("  output device shown above. Fix: set the device you hear the")
        print("  call through as the Windows default OUTPUT, then re-run this.")
    print("=" * 60)
    input("\nPress Enter to close.")


if __name__ == "__main__":
    main()
