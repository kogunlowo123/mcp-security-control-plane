variable "project_name"       { type = string }
variable "environment"        { type = string }
variable "vpc_id"             { type = string }
variable "subnet_ids"         { type = list(string) }
variable "allowed_cidr_blocks" { type = list(string); default = [] }
variable "kms_key_arn"        { type = string }
variable "tags"               { type = map(string); default = {} }
