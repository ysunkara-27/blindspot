import { Component, type ReactNode } from 'react';

/** Keeps one broken layer (e.g. the reveal overlay) from blanking the whole reading room. */
export class ErrorBoundary extends Component<{ fallback?: ReactNode; children: ReactNode }, { failed: boolean }> {
  state = { failed: false };
  static getDerivedStateFromError() {
    return { failed: true };
  }
  componentDidCatch(error: unknown) {
    console.error('Blindspot layer failed to render', error);
  }
  render() {
    return this.state.failed ? (this.props.fallback ?? null) : this.props.children;
  }
}
