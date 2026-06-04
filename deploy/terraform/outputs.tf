output "service_urls" {
  description = "Cloud Run service URLs for each MCP server"
  value = {
    for name, svc in google_cloud_run_v2_service.mcp_server :
    name => svc.uri
  }
}

output "mcp_endpoints" {
  description = "Full MCP endpoint URLs (append /mcp to service URL)"
  value = {
    for name, svc in google_cloud_run_v2_service.mcp_server :
    name => "${svc.uri}/mcp"
  }
}
