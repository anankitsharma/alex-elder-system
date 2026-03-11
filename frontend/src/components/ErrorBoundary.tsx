"use client";

import React, { Component, type ReactNode } from "react";
import { AlertTriangle, RefreshCw } from "lucide-react";

interface Props {
  children: ReactNode;
  fallback?: ReactNode;
  /** Optional label shown in the error UI (e.g. "Chart", "Trade Panel") */
  label?: string;
}

interface State {
  hasError: boolean;
  error: Error | null;
}

export class ErrorBoundary extends Component<Props, State> {
  state: State = { hasError: false, error: null };

  static getDerivedStateFromError(error: Error): State {
    return { hasError: true, error };
  }

  componentDidCatch(error: Error, info: React.ErrorInfo) {
    console.error(`[ErrorBoundary${this.props.label ? `:${this.props.label}` : ""}]`, error, info.componentStack);
  }

  handleRetry = () => {
    this.setState({ hasError: false, error: null });
  };

  render() {
    if (this.state.hasError) {
      if (this.props.fallback) return this.props.fallback;

      return (
        <div className="flex flex-col items-center justify-center gap-2 p-4 h-full min-h-[100px]">
          <AlertTriangle className="w-5 h-5 text-amber" />
          <p className="text-xs text-muted text-center">
            {this.props.label ? `${this.props.label} failed to render` : "Something went wrong"}
          </p>
          <button
            onClick={this.handleRetry}
            className="flex items-center gap-1 px-2 py-1 text-[10px] text-accent hover:text-accent/80 border border-border rounded transition-colors"
          >
            <RefreshCw className="w-3 h-3" /> Retry
          </button>
        </div>
      );
    }

    return this.props.children;
  }
}
