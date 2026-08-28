# Open in Full Release (Cove extension)

Optional. Adds a single **Open in Full Release** button to the video detail
page in Cove. Clicking it resolves that video's file path through Cove's own
database and opens Full Release in a new tab with the file already selected,
so you land straight on Inspect.

Without it, Full Release still works: you just pick the file in its own
browser instead.

Nothing runs inside Cove. No job is queued, no work is done in the Cove
process. It is a lookup and a redirect.

## Layout

```
cove-extension/
├── refs/                          the four Cove DLLs go here, see refs/README.md
└── src/FullReleaseLink/
    ├── FullReleaseLink.csproj     net10.0, EnableDynamicLoading, host assemblies not copied
    ├── FullReleaseLinkExtension.cs  IActionExtension (the button) + IApiExtension (the lookup)
    ├── extension.json             manifest read by Cove's ExtensionManager
    └── frontend/
        └── open-in-full-release.mjs  client-side action handler that does window.open
```

## Build and deploy

Both are documented in [../docs/DEPLOY.md](../docs/DEPLOY.md). The short
version: drop the DLLs from your container into `refs/`, build with a
throwaway .NET 10 SDK container, copy the output plus `extension.json` and
`frontend/` into `<cove-config>/extensions/com.christophmh.full-release-link/`,
restart Cove.

## Two things worth knowing if you write your own

**Compile against your own container.** There is no published SDK package;
the assemblies come out of the running image and the contract moves between
versions. Concretely: in Cove 1.0.0 `CoveContext` was not resolvable from an
extension's child container and you had to go through the repository
interfaces in `Cove.Core/Interfaces/`. In 1.3.1 it resolves directly, which is
what this extension does.

**Declare authorization on your endpoints.** Extension endpoints default to
anonymous access for backward compatibility, and Cove listens on `0.0.0.0`, so
an endpoint that declares nothing is callable by anything on the network. Cove
warns at startup about every endpoint that declares none.

`Cove.Sdk.EndpointAuthorizationExtensions` is how you declare it. The methods
are generic and chain onto the mapped endpoint:

```csharp
endpoints.MapPost(ResolveEndpoint, async (HttpContext http) => { ... })
         .RequireCovePermission(Permissions.VideosRead);
```

Alongside it there are `RequireCoveEntityAccess(entityType, idRouteValue)`,
`AllowWithoutCovePermission()` for authenticated but unrestricted endpoints,
and `AllowCoveAnonymous()` for genuinely public ones. Declaring one of the four
is what silences the startup warning.

This extension declares `videos.read` and additionally keeps a principal and
permission check inside the handler. That second check is what older Cove
versions required and is redundant now; it is kept as a second line of defence
and can be dropped if you raise `minCoveVersion` further.

What does not work either way is `RequiresPermission`: it is an MVC filter
attribute and minimal API endpoints ignore it.
