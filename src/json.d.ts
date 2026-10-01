// JSON data files are imported untyped (resolveJsonModule is off so the
// compiler doesn't infer types for half a megabyte of tables); each importer
// casts to the shape it documents.
declare module "*.json" {
  const value: unknown;
  export default value;
}

// Stylesheets are imported for their side effects; Vite bundles them.
declare module "*.css";
declare module "@fontsource/big-shoulders-stencil-display/*";
