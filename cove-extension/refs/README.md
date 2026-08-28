# Reference assemblies

This directory is intentionally empty in the repository. Copy the four Cove
assemblies out of **your own running Cove container** before building:

```sh
for f in Cove.Sdk.dll Cove.Plugins.dll Cove.Core.dll Cove.Data.dll; do
  docker cp Cove:/opt/cove/$f ./cove-extension/refs/$f
done
```

They are deliberately not committed. Cove's assemblies are not ours to
redistribute, and more practically: the extension API surface differs between
Cove builds, so a DLL from someone else's container is the wrong thing to
compile against. Building against the exact binaries you are going to load the
extension into turns a version mismatch into a compile error instead of a
runtime failure.
