bucket         = "VibeStream-terraform-state"
key            = "production/terraform.tfstate"
region         = "us-east-1"
encrypt        = true
dynamodb_table = "VibeStream-terraform-locks"
