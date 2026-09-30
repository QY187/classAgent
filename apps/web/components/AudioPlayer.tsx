"use client";

import { useEffect, useRef, useState } from "react";

type Seg = { id: string; start_ms: number };

function fmt(sec: number) {
  if (!Number.isFinite(sec)) return "00:00";
  const s = Math.max(0, Math.floor(sec));
  return `${String(Math.floor(s / 60)).padStart(2, "0")}:${String(s % 60).padStart(2, "0")}`;
}

export default function AudioPlayer({ src, segments, seek, onActiveChange }: {
  src: string;
  segments: Seg[];
  seek: { ms: number; n: number } | null;
  onActiveChange?: (id: string | null) => void;
}) {
  const audioRef = useRef<HTMLAudioElement>(null);
  const [playing, setPlaying] = useState(false);
  const [current, setCurrent] = useState(0);
  const [duration, setDuration] = useState(0);

  useEffect(() => {
    if (!seek) return;
    const audio = audioRef.current;
    if (!audio) return;
    audio.currentTime = seek.ms / 1000;
    void audio.play().catch(() => undefined);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [seek?.n]);

  function handleTimeUpdate() {
    const audio = audioRef.current;
    if (!audio) return;
    setCurrent(audio.currentTime);
    const ms = audio.currentTime * 1000;
    let active: string | null = null;
    for (const seg of segments) {
      if (seg.start_ms <= ms) active = seg.id;
      else break;
    }
    onActiveChange?.(active);
  }

  function toggle() {
    const audio = audioRef.current;
    if (!audio) return;
    if (audio.paused) void audio.play().catch(() => undefined);
    else audio.pause();
  }

  function seekByRatio(ratio: number) {
    const audio = audioRef.current;
    if (!audio || !audio.duration) return;
    audio.currentTime = ratio * audio.duration;
  }

  const progress = duration ? (current / duration) * 100 : 0;

  return (
    <div className="audio-player">
      <button type="button" className="audio-toggle" onClick={toggle} aria-label={playing ? "暂停" : "播放"}>{playing ? "⏸" : "▶"}</button>
      <span className="audio-time">{fmt(current)}</span>
      <div className="audio-progress" onClick={(event) => seekByRatio(event.nativeEvent.offsetX / event.currentTarget.clientWidth)} role="presentation">
        <span className="audio-progress-fill" style={{ width: `${progress}%` }} />
      </div>
      <span className="audio-time">{fmt(duration)}</span>
      <audio
        ref={audioRef}
        src={src}
        preload="metadata"
        onPlay={() => setPlaying(true)}
        onPause={() => setPlaying(false)}
        onEnded={() => setPlaying(false)}
        onTimeUpdate={handleTimeUpdate}
        onLoadedMetadata={(event) => setDuration(event.currentTarget.duration)}
      />
    </div>
  );
}
