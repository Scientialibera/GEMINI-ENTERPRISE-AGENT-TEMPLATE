variable "project_id" { type = string }
variable "region" { type = string }
variable "display_name" { type = string }
variable "description" { type = string }
variable "source_archive_path" { type = string }
variable "entrypoint_module" { type = string }
variable "entrypoint_object" { type = string }
variable "python_version" { type = string }
variable "requirements_file" { type = string }
variable "runtime_env" { type = map(string) }
variable "secret_env" {
  type = map(object({
    secret  = string
    version = string
  }))
}
variable "invoker_members" { type = set(string) }
variable "invoker_role" {
  type     = string
  nullable = true
}
variable "agent_project_roles" { type = set(string) }
variable "min_instances" { type = number }
variable "max_instances" { type = number }
variable "container_concurrency" { type = number }
variable "resource_limits" { type = map(string) }
