import { Ref } from "react";

export function CameraPreview({ videoRef }: { videoRef: Ref<HTMLVideoElement> }) {
  return (
    <section className="rounded-xl border border-neutral-800 bg-neutral-900 p-4">
      <h2 className="mb-3 text-sm font-medium text-neutral-300">Camera preview</h2>
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
