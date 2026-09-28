import { AlertTriangle, RotateCcw } from "lucide-react";
import React, { Component, ErrorInfo, ReactNode } from "react";

interface Props {
  children: ReactNode;
}

interface State {
  hasError: boolean;
  error: Error | null;
}

export default class ErrorBoundary extends Component<Props, State> {
  public state: State = {
    hasError: false,
    error: null,
  };

  public static getDerivedStateFromError(error: Error): State {
    return { hasError: true, error };
  }

  public componentDidCatch(error: Error, errorInfo: ErrorInfo) {
    console.error("Error boundary caught:", error, errorInfo);
  }

  private handleReset = () => {
    this.setState({ hasError: false, error: null });
    window.location.href = "/dashboard";
  };

  public render() {
    if (this.state.hasError) {
      return (
        <div className="flex min-h-screen items-center justify-center bg-backdrop px-4">
          <div className="sm-card max-w-lg px-8 py-10 text-center">
            <div className="mx-auto flex h-12 w-12 items-center justify-center rounded-2xl bg-bad-soft text-bad">
              <AlertTriangle className="h-5 w-5" strokeWidth={2} />
            </div>
            <h1 className="mt-5 font-display text-[24px] font-semibold tracking-[-0.02em] text-ink">This page stopped working</h1>
            <p className="mx-auto mt-2 max-w-md text-[14px] leading-6 text-muted">
              Something in the page crashed. Your data is safe — reload the dashboard to carry on.
            </p>
            {this.state.error && (
              <details className="mt-6 rounded-xl border border-line bg-sunken p-4 text-left">
                <summary className="cursor-pointer text-[13px] font-semibold text-ink">Technical details</summary>
                <pre className="mt-3 overflow-auto text-[12px] leading-5 text-muted">{this.state.error.toString()}</pre>
              </details>
            )}
            <button onClick={this.handleReset} className="sm-btn sm-btn-primary sm-btn-lg mx-auto mt-7">
              <RotateCcw className="h-4 w-4" strokeWidth={2} />
              Back to dashboard
            </button>
          </div>
        </div>
      );
    }

    return this.props.children;
  }
}
