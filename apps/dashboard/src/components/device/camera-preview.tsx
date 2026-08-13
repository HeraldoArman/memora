import { Ref } from "react";

export function CameraPreview({ videoRef }: { videoRef: Ref<HTMLVideoElement> }) {
  return (
    <section className="rounded-xl border border-ink-700 bg-ink-850 p-4 shadow-sm">
      <h2 className="mb-3 text-sm font-medium text-neutral-700">Camera preview</h2>
      <video
        ref={videoRef}
        className="aspect-video w-full rounded-lg bg-black"
        autoPlay
        muted
        playsInline
      />
    </section>
  );
}
