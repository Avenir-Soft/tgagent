"use client";

import { useState } from "react";
import { API_BASE } from "@/lib/api";
import { getInitial } from "@/lib/utils";

interface AvatarProps {
  src?: string | null;
  name?: string | null;
  fallback?: string;
  size?: "sm" | "md" | "lg";
  className?: string;
  colors?: { bg: string; text: string };
}

const sizes = {
  sm: "w-8 h-8 text-sm",
  md: "w-10 h-10 text-lg",
  lg: "w-12 h-12 text-lg",
};

export function Avatar({
  src,
  name,
  fallback = "?",
  size = "md",
  className = "",
  colors = { bg: "bg-indigo-50", text: "text-indigo-600" },
}: AvatarProps) {
  const [imgError, setImgError] = useState(false);
  const showImg = src && !imgError;
  const sizeClass = sizes[size];

  if (showImg) {
    return (
      <img
        src={`${API_BASE}${src}`}
        alt=""
        className={`${sizeClass} rounded-full object-cover shrink-0 ${className}`}
        onError={() => setImgError(true)}
      />
    );
  }

  return (
    <div className={`${sizeClass} rounded-full ${colors.bg} ${colors.text} flex items-center justify-center font-bold shrink-0 ${className}`}>
      {getInitial(name, fallback)}
    </div>
  );
}
