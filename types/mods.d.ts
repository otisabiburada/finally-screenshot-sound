// Minimal type declarations for the globals Decky Loader provides inside Steam.
declare module "@decky/ui" { export const ButtonItem: any, DropdownItem: any, Field: any, PanelSection: any, PanelSectionRow: any, SliderField: any, ToggleField: any, staticClasses: any; }
declare module "@decky/api" {
  export function definePlugin(f: (...a: any[]) => any): any;
  export function call<A extends any[], R>(name: string, ...args: any[]): Promise<R>;
  export function addEventListener<A extends any[]>(name: string, cb: (...a: A) => void): any;
  export function removeEventListener(name: string, cb: any): void;
}
declare module "react" { export function useState<T>(v: T | (() => T)): [T, (x: T | ((p: T) => T)) => void]; export function useEffect(f: () => any, d?: any[]): void; }
declare module "react-icons/fa" { export const FaCamera: any; }
