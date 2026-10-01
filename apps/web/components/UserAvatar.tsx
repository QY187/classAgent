"use client";

import { useEffect, useState } from "react";
import { requestBlob } from "../lib/api";

export const avatarUpdatedEvent = "classagent-avatar-updated";

export default function UserAvatar({ username, hasAvatar = false, className = "" }: { username: string; hasAvatar?: boolean; className?: string }) {
  const [avatarUrl, setAvatarUrl] = useState<string | null>(null);
  const [version, setVersion] = useState(0);

  useEffect(() => {
    const refresh = () => setVersion((current) => current + 1);
    window.addEventListener(avatarUpdatedEvent, refresh);
    return () => window.removeEventListener(avatarUpdatedEvent, refresh);
  }, []);

  useEffect(() => {
    if (!hasAvatar && version === 0) return;
    let active = true;
    let objectUrl: string | null = null;
    requestBlob("/auth/avatar").then((blob) => {
      objectUrl = URL.createObjectURL(blob);
      if (active) setAvatarUrl(objectUrl);
      else URL.revokeObjectURL(objectUrl);
    }).catch(() => { if (active) setAvatarUrl(null); });
    return () => { active = false; if (objectUrl) URL.revokeObjectURL(objectUrl); };
  }, [username, hasAvatar, version]);

  return <span className={`avatar ${className}`} aria-label={`${username}的头像`}>{avatarUrl ? <img src={avatarUrl} alt="" /> : username.slice(0, 1).toUpperCase()}</span>;
}
