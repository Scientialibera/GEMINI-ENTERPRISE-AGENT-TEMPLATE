output "reasoning_engine_name" {
  value = google_vertex_ai_reasoning_engine.this.name
}

output "reasoning_engine_id" {
  value = basename(google_vertex_ai_reasoning_engine.this.name)
}

output "agent_identity" {
  value = google_vertex_ai_reasoning_engine.this.effective_identity
}
