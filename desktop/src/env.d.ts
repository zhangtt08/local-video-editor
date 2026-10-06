/// <reference types="vite/client" />

import type { Bridge } from "../electron/shared";

declare global {
  interface Window {
    desktop: Bridge;
  }
}

export {};
