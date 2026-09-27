variable "project_name"   { type = string }
variable "environment"    { type = string }
variable "s3_kms_key_arn" { type = string }
variable "tags"           { type = map(string); default = {} }
