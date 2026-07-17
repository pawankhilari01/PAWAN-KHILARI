# AWS reference infrastructure for the EDT Platform (skeleton).
# See docs/15-deployment-architecture.md for the full topology and rationale.
# This is a module layout sketch — pin provider/module versions before real use.

terraform {
  required_version = ">= 1.6"
  required_providers {
    aws = { source = "hashicorp/aws", version = "~> 5.0" }
  }
  # backend "s3" { bucket = "edt-tfstate" key = "prod/terraform.tfstate" region = "us-east-1" dynamodb_table = "edt-tflock" }
}

provider "aws" {
  region = var.region
}

variable "region"      { type = string  default = "us-east-1" }
variable "environment" { type = string  default = "prod" }
variable "cluster_name" { type = string default = "edt-eks" }

# --- Networking ---
module "vpc" {
  source  = "terraform-aws-modules/vpc/aws"
  name    = "edt-${var.environment}"
  cidr    = "10.40.0.0/16"
  azs             = ["${var.region}a", "${var.region}b", "${var.region}c"]
  private_subnets = ["10.40.1.0/24", "10.40.2.0/24", "10.40.3.0/24"]
  public_subnets  = ["10.40.101.0/24", "10.40.102.0/24", "10.40.103.0/24"]
  enable_nat_gateway = true
  single_nat_gateway = false
}

# --- Kubernetes (agents, control plane, Temporal worker) ---
module "eks" {
  source          = "terraform-aws-modules/eks/aws"
  cluster_name    = var.cluster_name
  cluster_version = "1.30"
  vpc_id          = module.vpc.vpc_id
  subnet_ids      = module.vpc.private_subnets
  eks_managed_node_groups = {
    general   = { instance_types = ["m6i.xlarge"],  min_size = 3, max_size = 12, desired_size = 4 }
    reasoning = { instance_types = ["m6i.2xlarge"], min_size = 1, max_size = 8,  desired_size = 2 }
  }
}

# --- Postgres (runs, artifacts metadata, episodic memory) ---
resource "aws_db_instance" "postgres" {
  identifier            = "edt-${var.environment}"
  engine                = "postgres"
  engine_version        = "16"
  instance_class        = "db.r6g.xlarge"
  allocated_storage     = 200
  storage_encrypted     = true
  multi_az              = true
  db_name               = "edt"
  username              = "edt"
  manage_master_user_password = true   # secret stored in Secrets Manager
  backup_retention_period     = 14
  deletion_protection         = true
}

# --- Managed Kafka (event bus) ---
resource "aws_msk_cluster" "events" {
  cluster_name           = "edt-${var.environment}"
  kafka_version          = "3.6.0"
  number_of_broker_nodes = 3
  broker_node_group_info {
    instance_type   = "kafka.m5.large"
    client_subnets  = module.vpc.private_subnets
    storage_info { ebs_storage_info { volume_size = 200 } }
  }
  encryption_info { encryption_in_transit { client_broker = "TLS" } }
}

# --- ElastiCache Redis (working memory / locks / rate limits) ---
resource "aws_elasticache_replication_group" "redis" {
  replication_group_id = "edt-${var.environment}"
  description          = "EDT working memory + coordination"
  engine               = "redis"
  node_type            = "cache.r6g.large"
  num_cache_clusters   = 2
  automatic_failover_enabled = true
  at_rest_encryption_enabled = true
  transit_encryption_enabled = true
}

# --- S3 (artifact blobs, prompt registry) ---
resource "aws_s3_bucket" "artifacts" {
  bucket = "edt-artifacts-${var.environment}"
}
resource "aws_s3_bucket_versioning" "artifacts" {
  bucket = aws_s3_bucket.artifacts.id
  versioning_configuration { status = "Enabled" }
}

# Qdrant (vector DB) and Neo4j (knowledge graph) run as StatefulSets on EKS with
# EBS-gp3 volumes, or via their managed clouds — see docs/15 for the trade-off.

output "eks_cluster"   { value = module.eks.cluster_name }
output "postgres_host" { value = aws_db_instance.postgres.address }
output "artifacts_bucket" { value = aws_s3_bucket.artifacts.bucket }
