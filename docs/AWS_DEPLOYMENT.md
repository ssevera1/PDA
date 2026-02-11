# Deploying PDAgent on AWS

This guide covers three deployment options on AWS, from simplest to most production-ready:

1. **[EC2 (Simple)](#option-1-ec2--simple-server)** — A single server, easiest to understand
2. **[ECS Fargate (Recommended)](#option-2-ecs-fargate--recommended)** — Serverless containers, no server management
3. **[Elastic Beanstalk (Quick)](#option-3-elastic-beanstalk--quick-deploy)** — PaaS-style, fast deployment

All options result in a publicly accessible HTTPS endpoint that Twilio can reach.

---

## Prerequisites (All Options)

1. **AWS Account** — [Sign up here](https://aws.amazon.com/)
2. **AWS CLI installed and configured:**
   ```bash
   # Install AWS CLI
   # Windows: download from https://aws.amazon.com/cli/
   # macOS:
   brew install awscli
   # Linux:
   curl "https://awscli.amazonaws.com/awscli-exe-linux-x86_64.zip" -o "awscliv2.zip"
   unzip awscliv2.zip && sudo ./aws/install

   # Configure with your credentials
   aws configure
   # Enter: Access Key ID, Secret Access Key, Region (e.g., us-east-1), Output format (json)
   ```
3. **Docker installed** (for Options 2 & 3)
4. **Your `.env` values ready** (API keys, tokens, etc.)

---

## Option 1: EC2 — Simple Server

Best for: Learning, testing, low-traffic personal use.

### Step 1: Launch an EC2 Instance

1. Go to [EC2 Console](https://console.aws.amazon.com/ec2/)
2. Click **Launch Instance**
3. Configure:
   - **Name:** `pdagent`
   - **AMI:** Amazon Linux 2023
   - **Instance type:** `t3.micro` (free tier eligible) or `t3.small`
   - **Key pair:** Create a new one or use existing — download the `.pem` file
   - **Network settings:**
     - Allow SSH (port 22) from your IP
     - Allow HTTPS (port 443) from anywhere
     - Allow HTTP (port 80) from anywhere
   - **Storage:** 8 GB (default is fine)
4. Click **Launch Instance**

### Step 2: Connect and Install

```bash
# Connect to your instance
ssh -i your-key.pem ec2-user@<your-ec2-public-ip>

# Install Python and dependencies
sudo dnf update -y
sudo dnf install -y python3.11 python3.11-pip git nginx

# Clone your project (or upload it via scp)
git clone <your-repo-url> ~/pdagent
cd ~/pdagent

# Set up Python environment
python3.11 -m venv venv
source venv/bin/activate
pip install -r requirements.txt

# Create your .env file
cp .env.example .env
nano .env   # Fill in all your values
```

### Step 3: Set Up Nginx as Reverse Proxy

```bash
sudo nano /etc/nginx/conf.d/pdagent.conf
```

Paste this configuration:

```nginx
server {
    listen 80;
    server_name your-domain.com;  # or use the EC2 public IP

    location / {
        proxy_pass http://127.0.0.1:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }
}
```

```bash
sudo nginx -t          # Test config
sudo systemctl start nginx
sudo systemctl enable nginx
```

### Step 4: Set Up SSL with Let's Encrypt

```bash
# Install certbot
sudo dnf install -y certbot python3-certbot-nginx

# Get SSL certificate (replace with your domain)
sudo certbot --nginx -d your-domain.com

# Auto-renewal is set up automatically
```

> **No domain?** Use an [Elastic IP](https://docs.aws.amazon.com/AWSEC2/latest/UserGuide/elastic-ip-addresses-eip.html) and a free subdomain from [nip.io](https://nip.io) or [DuckDNS](https://www.duckdns.org/).

### Step 5: Run as a Service

Create a systemd service so PDAgent starts automatically:

```bash
sudo nano /etc/systemd/system/pdagent.service
```

```ini
[Unit]
Description=PDAgent - Personal Digital Agent
After=network.target

[Service]
Type=simple
User=ec2-user
WorkingDirectory=/home/ec2-user/pdagent
Environment=PATH=/home/ec2-user/pdagent/venv/bin:/usr/bin
EnvironmentFile=/home/ec2-user/pdagent/.env
ExecStart=/home/ec2-user/pdagent/venv/bin/uvicorn main:app --host 127.0.0.1 --port 8000
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
```

```bash
sudo systemctl daemon-reload
sudo systemctl start pdagent
sudo systemctl enable pdagent

# Check status
sudo systemctl status pdagent

# View logs
journalctl -u pdagent -f
```

### Step 6: Update Twilio Webhooks

In the Twilio Console, update your phone number's webhooks to:
- **Incoming call:** `https://your-domain.com/voice/incoming`
- **Status callback:** `https://your-domain.com/voice/status`

---

## Option 2: ECS Fargate — Recommended

Best for: Production use. No servers to manage, auto-scales, highly available.

### Step 1: Create an ECR Repository

```bash
# Create a container registry for your Docker image
aws ecr create-repository --repository-name pdagent --region us-east-1

# Note the repository URI from the output, e.g.:
# 123456789012.dkr.ecr.us-east-1.amazonaws.com/pdagent
```

### Step 2: Build and Push the Docker Image

```bash
# Authenticate Docker to ECR
aws ecr get-login-password --region us-east-1 | \
  docker login --username AWS --password-stdin 123456789012.dkr.ecr.us-east-1.amazonaws.com

# Build and push
docker build -t pdagent .
docker tag pdagent:latest 123456789012.dkr.ecr.us-east-1.amazonaws.com/pdagent:latest
docker push 123456789012.dkr.ecr.us-east-1.amazonaws.com/pdagent:latest
```

### Step 3: Store Secrets in AWS Systems Manager

Store your sensitive configuration in Parameter Store (free):

```bash
aws ssm put-parameter --name "/pdagent/ANTHROPIC_API_KEY" \
  --type SecureString --value "sk-ant-your-key"

aws ssm put-parameter --name "/pdagent/TWILIO_ACCOUNT_SID" \
  --type SecureString --value "ACxxxxxxxx"

aws ssm put-parameter --name "/pdagent/TWILIO_AUTH_TOKEN" \
  --type SecureString --value "your-token"

aws ssm put-parameter --name "/pdagent/TWILIO_PHONE_NUMBER" \
  --type String --value "+12025551234"

aws ssm put-parameter --name "/pdagent/TELEGRAM_BOT_TOKEN" \
  --type SecureString --value "123456:ABC..."

aws ssm put-parameter --name "/pdagent/TELEGRAM_CHAT_ID" \
  --type String --value "123456789"

aws ssm put-parameter --name "/pdagent/AGENT_NAME" \
  --type String --value "Sophie"

aws ssm put-parameter --name "/pdagent/OWNER_NAME" \
  --type String --value "Your Name"
```

### Step 4: Create the ECS Cluster

```bash
aws ecs create-cluster --cluster-name pdagent-cluster \
  --capacity-providers FARGATE \
  --default-capacity-provider-strategy capacityProvider=FARGATE,weight=1
```

### Step 5: Create the Task Execution Role

Create `ecs-trust-policy.json`:
```json
{
  "Version": "2012-10-17",
  "Statement": [{
    "Effect": "Allow",
    "Principal": {"Service": "ecs-tasks.amazonaws.com"},
    "Action": "sts:AssumeRole"
  }]
}
```

```bash
# Create the role
aws iam create-role --role-name pdagent-task-role \
  --assume-role-policy-document file://ecs-trust-policy.json

# Attach required policies
aws iam attach-role-policy --role-name pdagent-task-role \
  --policy-arn arn:aws:iam::aws:policy/service-role/AmazonECSTaskExecutionRolePolicy

# Allow reading SSM parameters (for secrets)
aws iam put-role-policy --role-name pdagent-task-role \
  --policy-name SSMReadAccess \
  --policy-document '{
    "Version": "2012-10-17",
    "Statement": [{
      "Effect": "Allow",
      "Action": ["ssm:GetParameters"],
      "Resource": "arn:aws:ssm:us-east-1:*:parameter/pdagent/*"
    }]
  }'
```

### Step 6: Create Task Definition

Create `task-definition.json`:

```json
{
  "family": "pdagent",
  "networkMode": "awsvpc",
  "requiresCompatibilities": ["FARGATE"],
  "cpu": "256",
  "memory": "512",
  "executionRoleArn": "arn:aws:iam::YOUR_ACCOUNT_ID:role/pdagent-task-role",
  "taskRoleArn": "arn:aws:iam::YOUR_ACCOUNT_ID:role/pdagent-task-role",
  "containerDefinitions": [{
    "name": "pdagent",
    "image": "YOUR_ACCOUNT_ID.dkr.ecr.us-east-1.amazonaws.com/pdagent:latest",
    "portMappings": [{"containerPort": 8000, "protocol": "tcp"}],
    "healthCheck": {
      "command": ["CMD-SHELL", "python -c \"import urllib.request; urllib.request.urlopen('http://localhost:8000/health')\""],
      "interval": 30,
      "timeout": 5,
      "retries": 3,
      "startPeriod": 10
    },
    "logConfiguration": {
      "logDriver": "awslogs",
      "options": {
        "awslogs-group": "/ecs/pdagent",
        "awslogs-region": "us-east-1",
        "awslogs-stream-prefix": "ecs",
        "awslogs-create-group": "true"
      }
    },
    "secrets": [
      {"name": "ANTHROPIC_API_KEY", "valueFrom": "arn:aws:ssm:us-east-1:YOUR_ACCOUNT_ID:parameter/pdagent/ANTHROPIC_API_KEY"},
      {"name": "TWILIO_ACCOUNT_SID", "valueFrom": "arn:aws:ssm:us-east-1:YOUR_ACCOUNT_ID:parameter/pdagent/TWILIO_ACCOUNT_SID"},
      {"name": "TWILIO_AUTH_TOKEN", "valueFrom": "arn:aws:ssm:us-east-1:YOUR_ACCOUNT_ID:parameter/pdagent/TWILIO_AUTH_TOKEN"},
      {"name": "TWILIO_PHONE_NUMBER", "valueFrom": "arn:aws:ssm:us-east-1:YOUR_ACCOUNT_ID:parameter/pdagent/TWILIO_PHONE_NUMBER"},
      {"name": "TELEGRAM_BOT_TOKEN", "valueFrom": "arn:aws:ssm:us-east-1:YOUR_ACCOUNT_ID:parameter/pdagent/TELEGRAM_BOT_TOKEN"},
      {"name": "TELEGRAM_CHAT_ID", "valueFrom": "arn:aws:ssm:us-east-1:YOUR_ACCOUNT_ID:parameter/pdagent/TELEGRAM_CHAT_ID"},
      {"name": "AGENT_NAME", "valueFrom": "arn:aws:ssm:us-east-1:YOUR_ACCOUNT_ID:parameter/pdagent/AGENT_NAME"},
      {"name": "OWNER_NAME", "valueFrom": "arn:aws:ssm:us-east-1:YOUR_ACCOUNT_ID:parameter/pdagent/OWNER_NAME"}
    ]
  }]
}
```

> Replace every `YOUR_ACCOUNT_ID` with your 12-digit AWS account ID.

```bash
aws ecs register-task-definition --cli-input-json file://task-definition.json
```

### Step 7: Create an Application Load Balancer

This gives you HTTPS with a fixed URL.

```bash
# Get your default VPC and subnets
VPC_ID=$(aws ec2 describe-vpcs --filters "Name=isDefault,Values=true" --query "Vpcs[0].VpcId" --output text)
SUBNETS=$(aws ec2 describe-subnets --filters "Name=vpc-id,Values=$VPC_ID" --query "Subnets[*].SubnetId" --output text | tr '\t' ',')

# Create a security group for the ALB
ALB_SG=$(aws ec2 create-security-group \
  --group-name pdagent-alb-sg \
  --description "PDAgent ALB" \
  --vpc-id $VPC_ID \
  --query "GroupId" --output text)

aws ec2 authorize-security-group-ingress --group-id $ALB_SG --protocol tcp --port 443 --cidr 0.0.0.0/0
aws ec2 authorize-security-group-ingress --group-id $ALB_SG --protocol tcp --port 80 --cidr 0.0.0.0/0

# Create a security group for the ECS tasks
ECS_SG=$(aws ec2 create-security-group \
  --group-name pdagent-ecs-sg \
  --description "PDAgent ECS Tasks" \
  --vpc-id $VPC_ID \
  --query "GroupId" --output text)

aws ec2 authorize-security-group-ingress --group-id $ECS_SG --protocol tcp --port 8000 --source-group $ALB_SG

# Create the ALB
ALB_ARN=$(aws elbv2 create-load-balancer \
  --name pdagent-alb \
  --subnets $(echo $SUBNETS | tr ',' ' ') \
  --security-groups $ALB_SG \
  --query "LoadBalancers[0].LoadBalancerArn" --output text)

# Create target group
TG_ARN=$(aws elbv2 create-target-group \
  --name pdagent-tg \
  --protocol HTTP --port 8000 \
  --vpc-id $VPC_ID \
  --target-type ip \
  --health-check-path /health \
  --query "TargetGroups[0].TargetGroupArn" --output text)

# Create HTTP listener (redirect to HTTPS later once you add a cert)
aws elbv2 create-listener \
  --load-balancer-arn $ALB_ARN \
  --protocol HTTP --port 80 \
  --default-actions Type=forward,TargetGroupArn=$TG_ARN
```

> **For HTTPS:** Request a certificate in [ACM](https://console.aws.amazon.com/acm/), then add an HTTPS listener on port 443. This requires a custom domain — point your domain's DNS to the ALB's DNS name.

### Step 8: Create the ECS Service

```bash
aws ecs create-service \
  --cluster pdagent-cluster \
  --service-name pdagent-service \
  --task-definition pdagent \
  --desired-count 1 \
  --launch-type FARGATE \
  --network-configuration "awsvpcConfiguration={subnets=[$(echo $SUBNETS | tr ',' ',')],securityGroups=[$ECS_SG],assignPublicIp=ENABLED}" \
  --load-balancers "targetGroupArn=$TG_ARN,containerName=pdagent,containerPort=8000"
```

### Step 9: Get Your URL and Update Twilio

```bash
# Get the ALB DNS name
aws elbv2 describe-load-balancers --names pdagent-alb \
  --query "LoadBalancers[0].DNSName" --output text
```

Update Twilio webhooks to:
- `http://pdagent-alb-XXXX.us-east-1.elb.amazonaws.com/voice/incoming`
- `http://pdagent-alb-XXXX.us-east-1.elb.amazonaws.com/voice/status`

> For production, set up a custom domain with HTTPS via ACM + Route 53.

### Updating the Deployment

When you push code changes:

```bash
# Build, tag, push new image
docker build -t pdagent .
docker tag pdagent:latest YOUR_ACCOUNT_ID.dkr.ecr.us-east-1.amazonaws.com/pdagent:latest
docker push YOUR_ACCOUNT_ID.dkr.ecr.us-east-1.amazonaws.com/pdagent:latest

# Force a new deployment (pulls latest image)
aws ecs update-service --cluster pdagent-cluster --service pdagent-service --force-new-deployment
```

---

## Option 3: Elastic Beanstalk — Quick Deploy

Best for: Getting to production fast without deep AWS knowledge.

### Step 1: Install the EB CLI

```bash
pip install awsebcli
```

### Step 2: Create a Procfile

Create `Procfile` in the project root:

```
web: uvicorn main:app --host 0.0.0.0 --port 8000
```

### Step 3: Initialize and Deploy

```bash
cd PDAgent

# Initialize Elastic Beanstalk
eb init pdagent --platform python-3.11 --region us-east-1

# Create the environment
eb create pdagent-prod \
  --instance-type t3.micro \
  --single \
  --envvars ANTHROPIC_API_KEY=sk-ant-xxx,TWILIO_ACCOUNT_SID=ACxxx,TWILIO_AUTH_TOKEN=xxx,TWILIO_PHONE_NUMBER=+1xxx,TELEGRAM_BOT_TOKEN=xxx,TELEGRAM_CHAT_ID=xxx,AGENT_NAME=Sophie,OWNER_NAME=YourName

# Wait for deployment (~5 minutes)
eb status
```

### Step 4: Enable HTTPS

1. Go to [ACM Console](https://console.aws.amazon.com/acm/) → Request a certificate for your domain
2. In EB Console → Configuration → Load Balancer → Add HTTPS listener on 443 with your cert
3. Update Twilio webhooks to use the HTTPS URL

### Updating

```bash
eb deploy
```

---

## Monitoring & Logs

### CloudWatch Logs (ECS Fargate)

```bash
# View recent logs
aws logs tail /ecs/pdagent --follow
```

### EC2 Logs

```bash
journalctl -u pdagent -f
```

### Elastic Beanstalk Logs

```bash
eb logs
```

### Setting Up CloudWatch Alarms

Create an alarm for high error rates:

```bash
aws cloudwatch put-metric-alarm \
  --alarm-name pdagent-errors \
  --metric-name 5XXError \
  --namespace AWS/ApplicationELB \
  --statistic Sum \
  --period 300 \
  --threshold 5 \
  --comparison-operator GreaterThanThreshold \
  --evaluation-periods 1 \
  --alarm-actions arn:aws:sns:us-east-1:YOUR_ACCOUNT_ID:your-sns-topic
```

---

## Cost Estimates (AWS)

| Resource | Monthly Cost | Notes |
|----------|-------------|-------|
| EC2 `t3.micro` | ~$8.50 | Or free tier eligible |
| ECS Fargate (256 CPU/512 MB) | ~$9.50 | No idle EC2 costs |
| Elastic Beanstalk | ~$8.50 | Uses EC2 under the hood |
| ALB | ~$16 + usage | Fixed cost for Fargate |
| CloudWatch Logs | ~$0.50/GB | Minimal for this app |
| ACM (SSL) | Free | Certificate manager |
| **Total (Fargate)** | **~$26/mo** | Fully managed |
| **Total (EC2)** | **~$9/mo** | Self-managed |

> All prices are for `us-east-1`. Your costs may vary by region and usage.
