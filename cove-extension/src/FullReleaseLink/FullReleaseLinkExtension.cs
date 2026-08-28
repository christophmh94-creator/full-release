using Cove.Core.Auth;
using Cove.Data;
using Cove.Plugins;
using Cove.Sdk;
using Microsoft.AspNetCore.Builder;
using Microsoft.AspNetCore.Http;
using Microsoft.AspNetCore.Routing;
using Microsoft.EntityFrameworkCore;
using Microsoft.Extensions.DependencyInjection;
using Microsoft.Extensions.Logging;
using CoveAuthorizationService = Cove.Core.Auth.IAuthorizationService;
using CovePermissions = Cove.Core.Auth.Permissions;

namespace FullReleaseLink;

/// <summary>
/// One button on the video detail page: "Open in Full Release". Resolves the video's file via
/// Cove's own MaxPath and returns a Full Release URL with that
/// file preselected; the frontend handler opens it in a new tab. Nothing runs inside Cove and
/// no job is queued anywhere - this is a pure hand-off to the operator console, whose base URL
/// comes from the FULL_RELEASE_URL environment variable on the Cove container.
/// </summary>
public sealed class FullReleaseLinkExtension : CoveExtensionBase, IActionExtension, IApiExtension
{
    private const string ResolveEndpoint = "/api/ext/full-release-link/resolve";

    // Cove mounts the whole Unraid user share as /media ("/mnt/user:/media:rw"). Full Release
    // mounts only /mnt/user/torrent as its own /media (docker-compose.yml / unraid template) -
    // so only files under /media/torrent are reachable from Cove's side, and the prefix strip
    // below both maps AND validates that in one step. Adjust to match your own mounts.
    private const string CoveMediaRoot = "/media/torrent/";

    private static readonly string FullReleaseBaseUrl =
        (Environment.GetEnvironmentVariable("FULL_RELEASE_URL") ?? "http://192.168.1.10:8008").TrimEnd('/');

    private ILogger? _log;

    public override Task InitializeAsync(IServiceProvider services, CancellationToken ct = default)
    {
        _log = services.GetService<ILoggerFactory>()?.CreateLogger("FullReleaseLink");
        _log?.LogInformation("Full Release Link {Version} initialised, target {Url}.", Version, FullReleaseBaseUrl);
        return base.InitializeAsync(services, ct);
    }

    // ---------------------------------------------------------------- UI action

    public IReadOnlyList<ExtensionAction> GetActions() =>
    [
        // Single video detail page only. HandlerName routes the
        // click to the client-side handler in frontend/open-in-full-release.mjs instead of
        // showing the default success toast - it needs to open a new tab, which a plain
        // apiEndpoint POST cannot do.
        new ExtensionAction(
            Id: "open-in-full-release",
            Label: "Open in Full Release",
            ExtensionId: Id,
            ActionType: "toolbar",
            EntityTypes: ["video"],
            Icon: "external-link",
            ApiEndpoint: ResolveEndpoint,
            HandlerName: "open",
            Order: 100)
        { RequiredPermission = CovePermissions.VideosRead },
    ];

    // ---------------------------------------------------------------- API endpoint

    /// <summary>Payload shape sent by ExtensionEntityActions.</summary>
    private sealed class ActionPayload
    {
        public List<int>? EntityIds { get; set; }
        public List<int>? SelectedIds { get; set; }
    }

    public void MapEndpoints(IEndpointRouteBuilder endpoints)
    {
        // In the released build, ExtensionManager.RegisterExtensionEndpoints calls MapEndpoints
        // without applying any authorization, and Cove listens on 0.0.0.0 - so a naively mapped
        // endpoint is callable from the whole LAN. Check explicitly, in the handler.
        // (RequiresPermissionAttribute does not help here: it is an MVC filter attribute and
        // has no effect on minimal API endpoints.)
        endpoints.MapPost(ResolveEndpoint, async (HttpContext http) =>
        {
            var services = http.RequestServices;

            var principal = services.GetService<ICurrentPrincipalAccessor>()?.Current;
            if (principal is null || principal.Kind == PrincipalKind.Anonymous)
                return Results.Json(new { message = "Not signed in." }, statusCode: StatusCodes.Status401Unauthorized);

            var authorization = services.GetService<CoveAuthorizationService>();
            if (authorization is not null && !authorization.Has(principal, CovePermissions.VideosRead))
                return Results.Json(
                    new { message = $"Missing permission: {CovePermissions.VideosRead}" },
                    statusCode: StatusCodes.Status403Forbidden);

            ActionPayload? payload;
            try
            {
                payload = await http.Request.ReadFromJsonAsync<ActionPayload>(http.RequestAborted);
            }
            catch (Exception ex)
            {
                _log?.LogWarning(ex, "Full Release Link: unreadable payload.");
                return Results.Json(new { message = "Invalid request." }, statusCode: StatusCodes.Status400BadRequest);
            }

            var videoId = (payload?.EntityIds ?? payload?.SelectedIds ?? []).FirstOrDefault();
            if (videoId <= 0)
                return Results.Json(new { message = "No video selected." }, statusCode: StatusCodes.Status400BadRequest);

            var db = services.GetRequiredService<CoveContext>();
            var video = await db.Videos.AsNoTracking()
                .Where(v => v.Id == videoId)
                .Select(v => new { v.Id, v.Title, v.MaxPath })
                .FirstOrDefaultAsync(http.RequestAborted);

            if (video is null)
                return Results.Json(new { message = $"Video {videoId} not found." }, statusCode: StatusCodes.Status404NotFound);
            if (string.IsNullOrEmpty(video.MaxPath))
                return Results.Json(new { message = "Video has no file." }, statusCode: StatusCodes.Status400BadRequest);
            if (!video.MaxPath.StartsWith(CoveMediaRoot, StringComparison.Ordinal))
                return Results.Json(new
                {
                    message = $"Video file is outside Full Release's media root (needs {CoveMediaRoot}..., got {video.MaxPath})",
                }, statusCode: StatusCodes.Status422UnprocessableEntity);

            var relativePath = video.MaxPath[CoveMediaRoot.Length..];
            var fullReleasePath = "/media/" + relativePath;
            var url = $"{FullReleaseBaseUrl}/?path={Uri.EscapeDataString(fullReleasePath)}";

            _log?.LogInformation("Full Release Link: video {VideoId} ({Path}) -> {Url}", videoId, relativePath, url);

            return Results.Json(new { url, title = video.Title });
        });
    }
}
