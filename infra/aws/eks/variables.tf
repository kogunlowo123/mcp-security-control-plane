variable "project_name" {
  description = "Name of the project"
  type        = string
}

variable "environment" {
  description = "Deployment environment"
  type        = string
}

variable "vpc_id" {
  description = "ID of the VPC"
  type        = string
}

variable "subnet_ids" {
  description = "List of private subnet IDs for EKS nodes"
  type        = list(string)
}

variable "cluster_version" {
  description = "Kubernetes version for the EKS cluster"
  type        = string
  default     = "1.30"
}

variable "node_group_min" {
  description = "Minimum number of nodes in the managed node group"
  type        = number
  default     = 2
}

variable "node_group_max" {
  description = "Maximum number of nodes in the managed node group"
  type        = number
  default     = 10
}

variable "node_group_desired" {
  description = "Desired number of nodes in the managed node group"
  type        = number
  default     = 3
}

variable "node_instance_types" {
  description = "List of EC2 instance types for worker nodes"
  type        = list(string)
  default     = ["m5.xlarge", "m5a.xlarge", "m6i.xlarge"]
}

variable "enable_karpenter" {
  description = "Whether to enable Karpenter for node autoscaling"
  type        = bool
  default     = true
}

variable "kms_key_arn" {
  description = "KMS key ARN for EKS secrets encryption"
  type        = string
}

variable "tags" {
  description = "Additional resource tags"
  type        = map(string)
  default     = {}
}
