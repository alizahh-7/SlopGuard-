import { Component, type ReactNode } from "react";
import { cn } from "../../../lib/utils";

interface BoundaryProps {
  children: ReactNode;
  fallback: ReactNode;
}

interface BoundaryState {
  hasError: boolean;
}

export class WebGLErrorBoundary extends Component<BoundaryProps, BoundaryState> {
  state: BoundaryState = { hasError: false };

  static getDerivedStateFromError(): BoundaryState {
    return { hasError: true };
  }

  render() {
    return this.state.hasError ? this.props.fallback : this.props.children;
  }
}

export function WebGLFallback({ className }: { className?: string }) {
  return (
    <div
      className={cn(className)}
      style={{
        background:
          "radial-gradient(120% 80% at 70% 100%, #00b4d8 0%, #001d3d 45%, #000814 100%)",
      }}
    />
  );
}
