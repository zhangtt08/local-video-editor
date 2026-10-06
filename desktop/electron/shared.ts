export type BackendInfo = {
  event?: string;
  port: number;
  base_url: string;
  token_file: string;
  media_ready: boolean;
  media_roots: string[];
  render_ready: boolean;
  output_roots: string[];
  data_dir: string;
  output_dir: string;
  ffmpeg: string;
  token?: string;
};

export type WindowState = {
  width: number;
  height: number;
  x?: number;
  y?: number;
  maximized: boolean;
};

export type CopyProgress = { file: string; done: number; total: number };

export type Bridge = {
  startEngine(): Promise<{ ok: boolean; info?: BackendInfo; error?: string }>;
  control(action: string): Promise<{ maximized: boolean; fullscreen: boolean } | null>;
  windowState(): Promise<{ maximized: boolean; fullscreen: boolean }>;
  resize(edge: string, dx: number, dy: number): Promise<unknown>;
  openMedia(): Promise<{ cancelled: boolean; copied?: { from: string; to: string }[]; library?: string; error?: string }>;
  pickOutputFolder(): Promise<{ cancelled: boolean; folder?: string }>;
  setOutputFolder(folder: string): Promise<{ ok: boolean; folder: string }>;
  readSettings(): Promise<{ outputFolder: string; mediaFolders: string[] }>;
  pickMediaRoot(): Promise<{ cancelled: boolean; folders?: string[]; info?: BackendInfo }>;
  showItem(path: string): Promise<boolean>;
  openExternal(url: string): Promise<boolean>;
  copyText(text: string): Promise<boolean>;
  token(): Promise<string>;
  restartEngine(): Promise<{ ok: boolean; info?: BackendInfo }>;
  appInfo(): Promise<{ version: string; electron: string; userData: string; library: string[]; enginePath: string }>;
  onEngineReady(handler: (info: BackendInfo) => void): () => void;
  onEngineError(handler: (message: string) => void): () => void;
  onMediaProgress(handler: (progress: CopyProgress) => void): () => void;
};
