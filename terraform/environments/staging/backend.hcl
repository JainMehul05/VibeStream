bucket         = "VibeStream-terraform-state"
key            = "staging/terraform.tfstate"
region         = "us-east-1"
encrypt        = true
dynamodb_table = "VibeStream-terraform-locks"
