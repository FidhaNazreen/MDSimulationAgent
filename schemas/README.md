# Schemas

The canonical JSON Schemas for mdagent live inside the package, not here:

    src/mdagent/_resources/schemas/v0.1.0/

That's where built wheels ship them from and where the loader resolves
them via `importlib.resources.files("mdagent._resources.schemas")`.

This top-level directory used to hold the schemas in v0; it now exists
only as a pointer so contributors don't go hunting.
