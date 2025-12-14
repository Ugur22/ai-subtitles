"""
Common Pydantic models used across the API
"""
from typing import Optional
from pydantic import BaseModel, Field


class ErrorResponse(BaseModel):
    """Standard error response"""
    detail: str = Field(..., description="Error message")
    error_code: Optional[str] = Field(None, description="Optional error code")

    model_config = {
        "json_schema_extra": {
            "example": {
                "detail": "An error occurred while processing your request",
                "error_code": "PROCESSING_ERROR"
            }
        }
    }


class SuccessResponse(BaseModel):
    """Standard success response"""
    success: bool = Field(True, description="Operation success status")
    message: str = Field(..., description="Success message")

    model_config = {
        "json_schema_extra": {
            "example": {
                "success": True,
                "message": "Operation completed successfully"
            }
        }
    }
