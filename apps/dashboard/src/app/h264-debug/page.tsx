import { H264Debugger } from "@/components/h264-debugger";

export const metadata = {
  title: "H.264 Signal Scope | Memora",
  description: "Dedicated LiveKit receiver for inspecting the physical ESP32 video track.",
};

export default function Page() {
  return <H264Debugger />;
}
