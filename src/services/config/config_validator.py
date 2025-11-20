"""
Configuration validation service.

Tests all components of a configuration profile to ensure they are working correctly.
"""

import logging
from typing import Dict, Any, List

import mlflow
from databricks_langchain import ChatDatabricks
from langchain_core.messages import HumanMessage

from src.config.client import get_databricks_client
from src.config.settings_db import load_settings_from_database
from src.services.tools import initialize_genie_conversation, query_genie_space

logger = logging.getLogger(__name__)


class ValidationResult:
    """Result of a validation check."""
    
    def __init__(self, component: str, success: bool, message: str, details: str = None):
        self.component = component
        self.success = success
        self.message = message
        self.details = details
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for API response."""
        result = {
            "component": self.component,
            "success": self.success,
            "message": self.message,
        }
        if self.details:
            result["details"] = self.details
        return result


class ConfigurationValidator:
    """Validates configuration by testing each component."""
    
    def __init__(self, profile_id: int):
        """
        Initialize validator for a specific profile.
        
        Args:
            profile_id: Profile ID to validate
        """
        self.profile_id = profile_id
        self.settings = None
        self.results: List[ValidationResult] = []
    
    def validate_all(self) -> Dict[str, Any]:
        """
        Validate all components of the configuration.
        
        Returns:
            Dictionary with validation results and overall status
        """
        logger.info(f"Starting validation for profile {self.profile_id}")
        
        # Load settings for this profile
        try:
            self.settings = load_settings_from_database(self.profile_id)
            logger.info(f"Loaded settings for profile {self.profile_id}")
        except Exception as e:
            logger.error(f"Failed to load settings for profile {self.profile_id}: {e}")
            return {
                "success": False,
                "profile_id": self.profile_id,
                "error": f"Failed to load profile settings: {str(e)}",
                "results": [],
            }
        
        # Run validation tests
        self._validate_llm()
        self._validate_genie()
        self._validate_mlflow()
        
        # Compile results
        all_success = all(r.success for r in self.results)
        
        return {
            "success": all_success,
            "profile_id": self.profile_id,
            "profile_name": self.settings.profile_name,
            "results": [r.to_dict() for r in self.results],
        }
    
    def _validate_llm(self) -> None:
        """Test LLM endpoint with a simple message."""
        logger.info("Validating LLM endpoint")
        
        try:
            # Create ChatDatabricks instance
            model = ChatDatabricks(
                endpoint=self.settings.llm.endpoint,
                temperature=self.settings.llm.temperature,
                max_tokens=100,  # Small for test
                top_p=self.settings.llm.top_p,
            )
            
            # Send test message
            message = HumanMessage(content="hello")
            response = model.invoke([message])
            
            # Check response
            if response and response.content:
                self.results.append(ValidationResult(
                    component="LLM",
                    success=True,
                    message=f"Successfully connected to LLM endpoint: {self.settings.llm.endpoint}",
                    details=f"Response received: {response.content[:100]}..."
                ))
                logger.info("LLM validation successful")
            else:
                self.results.append(ValidationResult(
                    component="LLM",
                    success=False,
                    message="Failed to call LLM: Empty response received",
                    details=f"Endpoint: {self.settings.llm.endpoint}"
                ))
                logger.warning("LLM validation failed: empty response")
                
        except Exception as e:
            error_msg = str(e)
            self.results.append(ValidationResult(
                component="LLM",
                success=False,
                message=f"Failed to call LLM: {error_msg}",
                details=f"Endpoint: {self.settings.llm.endpoint}"
            ))
            logger.error(f"LLM validation failed: {e}", exc_info=True)
    
    def _validate_genie(self) -> None:
        """Test Genie with a query."""
        logger.info("Validating Genie space")
        
        conversation_id = None
        try:
            # Initialize conversation
            conversation_id = initialize_genie_conversation(
                placeholder_message="System: Testing configuration"
            )
            
            # Query Genie
            result = query_genie_space(
                query="Return a table of how many rows you have per table",
                conversation_id=conversation_id,
                max_retries=1,
            )
            
            # Check result
            if result and result.get("data"):
                self.results.append(ValidationResult(
                    component="Genie",
                    success=True,
                    message=f"Successfully connected to Genie space: {self.settings.genie.space_id}",
                    details=f"Query executed and returned data"
                ))
                logger.info("Genie validation successful")
            else:
                self.results.append(ValidationResult(
                    component="Genie",
                    success=False,
                    message="Failed to query Genie: No data returned",
                    details=f"Space ID: {self.settings.genie.space_id}"
                ))
                logger.warning("Genie validation failed: no data")
                
        except Exception as e:
            error_msg = str(e)
            self.results.append(ValidationResult(
                component="Genie",
                success=False,
                message=f"Failed to query Genie: {error_msg}",
                details=f"Space ID: {self.settings.genie.space_id}"
            ))
            logger.error(f"Genie validation failed: {e}", exc_info=True)
        finally:
            # Clean up conversation if created
            if conversation_id:
                try:
                    client = get_databricks_client()
                    client.genie.delete_conversation(
                        space_id=self.settings.genie.space_id,
                        conversation_id=conversation_id
                    )
                    logger.info(f"Cleaned up test conversation: {conversation_id}")
                except Exception as e:
                    logger.warning(f"Failed to clean up test conversation: {e}")
    
    def _validate_mlflow(self) -> None:
        """Test MLflow experiment creation/write permissions."""
        logger.info("Validating MLflow experiment")
        
        try:
            # Set tracking URI
            mlflow.set_tracking_uri("databricks")
            
            # Try to get or create experiment
            experiment_name = self.settings.mlflow.experiment_name
            experiment = mlflow.get_experiment_by_name(experiment_name)
            
            if experiment is None:
                # Try to create experiment
                experiment_id = mlflow.create_experiment(experiment_name)
                self.results.append(ValidationResult(
                    component="MLflow",
                    success=True,
                    message=f"Successfully created MLflow experiment: {experiment_name}",
                    details=f"Experiment ID: {experiment_id}"
                ))
                logger.info(f"MLflow validation successful: created experiment {experiment_id}")
            else:
                # Experiment exists - try to set it (tests permissions)
                mlflow.set_experiment(experiment_name=experiment_name)
                self.results.append(ValidationResult(
                    component="MLflow",
                    success=True,
                    message=f"Successfully accessed MLflow experiment: {experiment_name}",
                    details=f"Experiment ID: {experiment.experiment_id}"
                ))
                logger.info(f"MLflow validation successful: accessed experiment {experiment.experiment_id}")
                
        except Exception as e:
            error_msg = str(e)
            self.results.append(ValidationResult(
                component="MLflow",
                success=False,
                message=f"Failed to create MLflow experiment: {error_msg}",
                details=f"Experiment name: {self.settings.mlflow.experiment_name}"
            ))
            logger.error(f"MLflow validation failed: {e}", exc_info=True)
    
    def validate_llm_endpoint(self, endpoint: str) -> ValidationResult:
        """
        Validate a specific LLM endpoint.
        
        Args:
            endpoint: LLM endpoint name to test
            
        Returns:
            ValidationResult with success status and details
        """
        logger.info(f"Validating LLM endpoint: {endpoint}")
        
        try:
            # Create ChatDatabricks instance
            model = ChatDatabricks(
                endpoint=endpoint,
                temperature=0.1,
                max_tokens=100,  # Small for test
            )
            
            # Send test message
            message = HumanMessage(content="hello")
            response = model.invoke([message])
            
            # Check response
            if response and response.content:
                logger.info(f"LLM endpoint {endpoint} validation successful")
                return ValidationResult(
                    component="LLM",
                    success=True,
                    message=f"Successfully connected to LLM endpoint: {endpoint}",
                    details=f"Response received: {response.content[:100]}..."
                )
            else:
                logger.warning(f"LLM endpoint {endpoint} validation failed: empty response")
                return ValidationResult(
                    component="LLM",
                    success=False,
                    message="Failed to call LLM: Empty response received",
                    details=f"Endpoint: {endpoint}"
                )
                
        except Exception as e:
            error_msg = str(e)
            logger.error(f"LLM endpoint {endpoint} validation failed: {e}", exc_info=True)
            return ValidationResult(
                component="LLM",
                success=False,
                message=f"Failed to call LLM: {error_msg}",
                details=f"Endpoint: {endpoint}"
            )
    
    def validate_genie_space(self, space_id: str) -> ValidationResult:
        """
        Validate a specific Genie space.
        
        Args:
            space_id: Genie space ID to test
            
        Returns:
            ValidationResult with success status and details
        """
        logger.info(f"Validating Genie space: {space_id}")
        
        try:
            # Check if space exists
            client = get_databricks_client()
            spaces = client.genie.list_spaces()
            
            space_exists = False
            if spaces.spaces:
                space_exists = any(s.space_id == space_id for s in spaces.spaces)
            
            # Check pagination
            while not space_exists and spaces.next_page_token:
                spaces = client.genie.list_spaces(page_token=spaces.next_page_token)
                if spaces.spaces:
                    space_exists = any(s.space_id == space_id for s in spaces.spaces)
            
            if space_exists:
                logger.info(f"Genie space {space_id} validation successful")
                return ValidationResult(
                    component="Genie",
                    success=True,
                    message=f"Successfully found Genie space: {space_id}",
                    details="Space is accessible"
                )
            else:
                logger.warning(f"Genie space {space_id} not found")
                return ValidationResult(
                    component="Genie",
                    success=False,
                    message=f"Genie space not found: {space_id}",
                    details="Space does not exist or is not accessible"
                )
                
        except Exception as e:
            error_msg = str(e)
            logger.error(f"Genie space {space_id} validation failed: {e}", exc_info=True)
            return ValidationResult(
                component="Genie",
                success=False,
                message=f"Failed to validate Genie space: {error_msg}",
                details=f"Space ID: {space_id}"
            )
    
    def validate_mlflow_experiment(self, experiment_name: str) -> ValidationResult:
        """
        Validate a specific MLflow experiment.
        
        Args:
            experiment_name: MLflow experiment path to test
            
        Returns:
            ValidationResult with success status and details
        """
        logger.info(f"Validating MLflow experiment: {experiment_name}")
        
        try:
            # Set tracking URI
            mlflow.set_tracking_uri("databricks")
            
            # Try to get or create experiment
            experiment = mlflow.get_experiment_by_name(experiment_name)
            
            if experiment:
                logger.info(f"MLflow experiment {experiment_name} found")
                return ValidationResult(
                    component="MLflow",
                    success=True,
                    message=f"Successfully accessed MLflow experiment: {experiment_name}",
                    details=f"Experiment ID: {experiment.experiment_id}"
                )
            else:
                # Try to create it to test permissions
                try:
                    experiment_id = mlflow.create_experiment(experiment_name)
                    logger.info(f"MLflow experiment {experiment_name} created successfully")
                    return ValidationResult(
                        component="MLflow",
                        success=True,
                        message=f"Successfully created MLflow experiment: {experiment_name}",
                        details=f"Experiment ID: {experiment_id}"
                    )
                except Exception as create_error:
                    logger.error(f"Failed to create experiment: {create_error}")
                    return ValidationResult(
                        component="MLflow",
                        success=False,
                        message=f"Failed to access or create experiment: {str(create_error)}",
                        details=f"Experiment: {experiment_name}"
                    )
                
        except Exception as e:
            error_msg = str(e)
            logger.error(f"MLflow experiment {experiment_name} validation failed: {e}", exc_info=True)
            return ValidationResult(
                component="MLflow",
                success=False,
                message=f"Failed to validate MLflow experiment: {error_msg}",
                details=f"Experiment: {experiment_name}"
            )


def validate_profile_configuration(profile_id: int) -> Dict[str, Any]:
    """
    Validate all components of a profile configuration.
    
    Args:
        profile_id: Profile ID to validate
        
    Returns:
        Dictionary with validation results
    """
    validator = ConfigurationValidator(profile_id)
    return validator.validate_all()

