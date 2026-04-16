using DeploymentRegistry.Api.Configuration;
using Microsoft.AspNetCore.Mvc;
using Microsoft.Extensions.Options;
using MongoDB.Driver;

namespace DeploymentRegistry.Api.Controllers;

[ApiController]
[Route("api/[controller]")]
public class HealthController : ControllerBase
{
    private readonly MongoDbSettings _settings;

    public HealthController(IOptions<MongoDbSettings> settings)
    {
        _settings = settings.Value;
    }

    [HttpGet]
    public async Task<ActionResult> Get()
    {
        try
        {
            var client = new MongoClient(_settings.ConnectionString);
            var database = client.GetDatabase(_settings.DatabaseName);
            await database.RunCommandAsync<MongoDB.Bson.BsonDocument>(
                new MongoDB.Bson.BsonDocument("ping", 1));

            return Ok(new
            {
                status = "healthy",
                timestamp = DateTime.UtcNow,
                dependencies = new
                {
                    mongodb = "connected"
                }
            });
        }
        catch (Exception)
        {
            return StatusCode(503, new
            {
                status = "unhealthy",
                timestamp = DateTime.UtcNow,
                dependencies = new
                {
                    mongodb = "disconnected"
                }
            });
        }
    }
}
