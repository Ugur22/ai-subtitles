# AWS Deployment Guide

## 1. Required AWS Services

- **ECS (Elastic Container Service)** - For running Docker containers
- **RDS (Relational Database Service)** - For PostgreSQL database
- **ElastiCache** - For Redis
- **S3** - For file storage (replacing MinIO)
- **ECR (Elastic Container Registry)** - For storing Docker images
- **ALB (Application Load Balancer)** - For load balancing
- **Route 53** - For DNS management (if you have a domain)
- **ACM** - For SSL certificates

## 2. Step-by-Step Deployment

### 2.1. Initial AWS Setup

```bash
# Install AWS CLI
curl "https://awscli.amazonaws.com/awscli-exe-linux-x86_64.zip" -o "awscliv2.zip"
unzip awscliv2.zip
sudo ./aws/install

# Configure AWS CLI
aws configure
```

### 2.2. Create ECR Repository

```bash
# Create repository
aws ecr create-repository --repository-name transcription-service

# Login to ECR
aws ecr get-login-password --region YOUR_REGION | docker login --username AWS --password-stdin YOUR_ACCOUNT_ID.dkr.ecr.YOUR_REGION.amazonaws.com

# Tag and push image
docker tag transcription-service:latest YOUR_ACCOUNT_ID.dkr.ecr.YOUR_REGION.amazonaws.com/transcription-service:latest
docker push YOUR_ACCOUNT_ID.dkr.ecr.YOUR_REGION.amazonaws.com/transcription-service:latest
```

### 2.3. Create RDS Instance

```bash
aws rds create-db-instance \
    --db-instance-identifier transcription-db \
    --db-instance-class db.t3.micro \
    --engine postgres \
    --master-username admin \
    --master-user-password YOUR_PASSWORD \
    --allocated-storage 20
```

### 2.4. Create ElastiCache Cluster

```bash
aws elasticache create-cache-cluster \
    --cache-cluster-id transcription-redis \
    --cache-node-type cache.t3.micro \
    --engine redis \
    --num-cache-nodes 1
```

### 2.5. Create ECS Cluster and Task Definition

1. Create `task-definition.json`:

```json
{
  "family": "transcription-service",
  "networkMode": "awsvpc",
  "requiresCompatibilities": ["FARGATE"],
  "cpu": "1024",
  "memory": "2048",
  "containerDefinitions": [
    {
      "name": "transcription-app",
      "image": "YOUR_ACCOUNT_ID.dkr.ecr.YOUR_REGION.amazonaws.com/transcription-service:latest",
      "portMappings": [
        {
          "containerPort": 8000,
          "protocol": "tcp"
        }
      ],
      "environment": [
        {
          "name": "DATABASE_URL",
          "value": "postgresql://admin:password@YOUR_RDS_ENDPOINT:5432/transcription_db"
        },
        {
          "name": "REDIS_URL",
          "value": "redis://YOUR_ELASTICACHE_ENDPOINT:6379/0"
        },
        {
          "name": "AWS_S3_BUCKET",
          "value": "your-transcription-bucket"
        }
      ],
      "logConfiguration": {
        "logDriver": "awslogs",
        "options": {
          "awslogs-group": "/ecs/transcription-service",
          "awslogs-region": "YOUR_REGION",
          "awslogs-stream-prefix": "ecs"
        }
      }
    }
  ]
}
```

2. Register the task definition:

```bash
aws ecs register-task-definition --cli-input-json file://task-definition.json
```

### 2.6. Create Application Load Balancer

1. Create ALB:

```bash
aws elbv2 create-load-balancer \
    --name transcription-alb \
    --subnets subnet-xxxx subnet-yyyy \
    --security-groups sg-xxxx
```

2. Create target group:

```bash
aws elbv2 create-target-group \
    --name transcription-tg \
    --protocol HTTP \
    --port 8000 \
    --vpc-id vpc-xxxx \
    --target-type ip
```

### 2.7. Create ECS Service

```bash
aws ecs create-service \
    --cluster transcription-cluster \
    --service-name transcription-service \
    --task-definition transcription-service:1 \
    --desired-count 2 \
    --launch-type FARGATE \
    --network-configuration "awsvpcConfiguration={subnets=[subnet-xxxx,subnet-yyyy],securityGroups=[sg-xxxx],assignPublicIp=ENABLED}" \
    --load-balancers "targetGroupArn=arn:aws:elasticloadbalancing:YOUR_REGION:YOUR_ACCOUNT_ID:targetgroup/transcription-tg/xxx,containerName=transcription-app,containerPort=8000"
```

## 3. Cost Estimation (Monthly)

- **ECS Fargate** (2 tasks): ~$40-60
- **RDS** (db.t3.micro): ~$15-20
- **ElastiCache** (cache.t3.micro): ~$15-20
- **ALB**: ~$20
- **S3**: Pay per use (~$0.023 per GB)
- **Data Transfer**: ~$0.09 per GB out
- **Total Base Cost**: ~$90-120/month

## 4. Scaling Configuration

```bash
# Create Auto Scaling Target
aws application-autoscaling register-scalable-target \
    --service-namespace ecs \
    --scalable-dimension ecs:service:DesiredCount \
    --resource-id service/transcription-cluster/transcription-service \
    --min-capacity 2 \
    --max-capacity 10

# Create CPU-based scaling policy
aws application-autoscaling put-scaling-policy \
    --service-namespace ecs \
    --scalable-dimension ecs:service:DesiredCount \
    --resource-id service/transcription-cluster/transcription-service \
    --policy-name cpu-scaling \
    --policy-type TargetTrackingScaling \
    --target-tracking-scaling-policy-configuration '{
        "TargetValue": 70.0,
        "PredefinedMetricSpecification": {
            "PredefinedMetricType": "ECSServiceAverageCPUUtilization"
        }
    }'
```

## 5. Monitoring Setup

1. Create CloudWatch Dashboard:

```bash
aws cloudwatch put-dashboard \
    --dashboard-name TranscriptionService \
    --dashboard-body file://dashboard.json
```

2. Set up alarms:

```bash
# CPU Utilization Alarm
aws cloudwatch put-metric-alarm \
    --alarm-name transcription-cpu-alarm \
    --alarm-description "CPU utilization exceeds 85%" \
    --metric-name CPUUtilization \
    --namespace AWS/ECS \
    --statistic Average \
    --period 300 \
    --threshold 85 \
    --comparison-operator GreaterThanThreshold \
    --evaluation-periods 2 \
    --alarm-actions arn:aws:sns:YOUR_REGION:YOUR_ACCOUNT_ID:YOUR_SNS_TOPIC
```

## 6. Backup Strategy

1. RDS Automated Backups:

```bash
aws rds modify-db-instance \
    --db-instance-identifier transcription-db \
    --backup-retention-period 7 \
    --preferred-backup-window "03:00-04:00"
```

2. S3 Versioning:

```bash
aws s3api put-bucket-versioning \
    --bucket your-transcription-bucket \
    --versioning-configuration Status=Enabled
```

## 7. Security Best Practices

1. Enable AWS WAF:

```bash
aws wafv2 create-web-acl \
    --name transcription-waf \
    --scope REGIONAL \
    --default-action Block={} \
    --rules file://waf-rules.json
```

2. Enable AWS Shield (recommended for production):

```bash
aws shield subscribe
```

## 8. Production Checklist

- [ ] Set up VPC with private subnets
- [ ] Configure security groups
- [ ] Set up CloudWatch logs
- [ ] Enable AWS X-Ray for tracing
- [ ] Set up backup retention policies
- [ ] Configure SSL/TLS certificates
- [ ] Set up CI/CD pipeline (AWS CodePipeline)
- [ ] Configure AWS Secrets Manager for sensitive data
- [ ] Set up CloudWatch alarms for monitoring
- [ ] Enable AWS GuardDuty for security monitoring

## 9. Frontend Deployment

### 9.1. Frontend Infrastructure

1. **Create S3 Bucket for Frontend**:

```bash
# Create bucket
aws s3 mb s3://transcription-frontend

# Enable static website hosting
aws s3 website s3://transcription-frontend --index-document index.html --error-document index.html
```

2. **Create CloudFront Distribution**:

```bash
# Create distribution with S3 origin
aws cloudfront create-distribution \
    --origin-domain-name transcription-frontend.s3.amazonaws.com \
    --default-root-object index.html \
    --default-cache-behavior '{"TargetOriginId":"S3-transcription-frontend","ViewerProtocolPolicy":"redirect-to-https","AllowedMethods":{"Quantity":2,"Items":["HEAD","GET"]},"CachedMethods":{"Quantity":2,"Items":["HEAD","GET"]},"ForwardedValues":{"QueryString":false,"Cookies":{"Forward":"none"}}}'
```

3. **Configure CORS for API**:

```bash
# Update API Gateway CORS settings
aws apigateway update-cors-configuration \
    --rest-api-id YOUR_API_ID \
    --resource-id YOUR_RESOURCE_ID \
    --cors-configuration '{"allowOrigins": ["https://your-frontend-domain.com"], "allowMethods": ["POST", "GET", "OPTIONS"], "allowHeaders": ["Content-Type", "Authorization"], "exposeHeaders": ["Content-Length", "Content-Type"], "maxAge": 600}'
```

### 9.2. Frontend Deployment Pipeline

1. **Create CodeBuild Project**:

```bash
aws codebuild create-project \
    --name transcription-frontend \
    --source type=GITHUB,location=https://github.com/your/repo \
    --artifacts type=S3,location=transcription-frontend \
    --environment type=LINUX_CONTAINER,image=aws/codebuild/standard:5.0 \
    --buildspec buildspec.yml
```

2. **Create buildspec.yml**:

```yaml
version: 0.2

phases:
  install:
    runtime-versions:
      nodejs: 16
    commands:
      - npm ci
  build:
    commands:
      - npm run build
  post_build:
    commands:
      - aws s3 sync dist/ s3://transcription-frontend
      - aws cloudfront create-invalidation --distribution-id YOUR_DIST_ID --paths "/*"

artifacts:
  files:
    - "**/*"
  base-directory: dist
```

### 9.3. DNS and SSL Setup

1. **Create SSL Certificate**:

```bash
# Request certificate
aws acm request-certificate \
    --domain-name your-app.com \
    --validation-method DNS \
    --subject-alternative-names www.your-app.com

# Add DNS validation records to Route 53
aws route53 change-resource-record-sets \
    --hosted-zone-id YOUR_ZONE_ID \
    --change-batch file://dns-validation.json
```

2. **Configure Route 53**:

```bash
# Create A record for CloudFront
aws route53 change-resource-record-sets \
    --hosted-zone-id YOUR_ZONE_ID \
    --change-batch '{
        "Changes": [{
            "Action": "CREATE",
            "ResourceRecordSet": {
                "Name": "your-app.com",
                "Type": "A",
                "AliasTarget": {
                    "HostedZoneId": "Z2FDTNDATAQYW2",
                    "DNSName": "YOUR_CLOUDFRONT_DOMAIN",
                    "EvaluateTargetHealth": false
                }
            }
        }]
    }'
```

### 9.4. Security Configuration

1. **S3 Bucket Policy**:

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Sid": "PublicReadGetObject",
      "Effect": "Allow",
      "Principal": "*",
      "Action": "s3:GetObject",
      "Resource": "arn:aws:s3:::transcription-frontend/*"
    }
  ]
}
```

2. **CloudFront Security Headers**:

```bash
# Add security headers in CloudFront function
aws cloudfront create-function \
    --name security-headers \
    --function-config '{"Comment":"Add security headers","Runtime":"cloudfront-js-1.0"}' \
    --function-code file://security-headers.js
```

### 9.5. Monitoring and Alerts

1. **CloudWatch Alarms**:

```bash
# Create 4xx error rate alarm
aws cloudwatch put-metric-alarm \
    --alarm-name frontend-4xx-errors \
    --metric-name 4xxErrorRate \
    --namespace AWS/CloudFront \
    --statistic Average \
    --period 300 \
    --threshold 5 \
    --comparison-operator GreaterThanThreshold \
    --evaluation-periods 2 \
    --alarm-actions arn:aws:sns:YOUR_REGION:YOUR_ACCOUNT_ID:YOUR_SNS_TOPIC
```
