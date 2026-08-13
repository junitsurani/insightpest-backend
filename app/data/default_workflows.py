"""
Default workflow configurations for The Sales application.
This file contains predefined workflow structures that can be applied to new user accounts.
"""




# Default sales workflow phases
DEFAULT_SALES_WORKFLOW_PHASES = [
    {"name": "Prospecting", "prompt": "Identify and research potential customers"},
    {"name": "Initial Contact", "prompt": "Reach out to prospects via email, phone, or social media"},
    {"name": "Qualification", "prompt": "Determine if the prospect has a need for your product/service"},
    {"name": "Needs Analysis", "prompt": "Identify specific problems and challenges the prospect is facing"},
    {"name": "Proposal/Presentation", "prompt": "Present your solution to address the prospect's needs"},
    {"name": "Handling Objections", "prompt": "Address any concerns or questions raised by the prospect"},
    {"name": "Closing", "prompt": "Secure the sale by asking for the business"},
    {"name": "Follow-up", "prompt": "Maintain the relationship for potential future sales and referrals"}
]

from app.routes.routes_CallAnalytics_Page.utils.analysis_prompts.analysis_prompts_setting import master_document_phase_one
from app.routes.routes_CallAnalytics_Page.utils.analysis_prompts.analysis_prompts_setting import master_document_phase_two
from app.routes.routes_CallAnalytics_Page.utils.analysis_prompts.analysis_prompts_setting import master_document_phase_three
from app.routes.routes_CallAnalytics_Page.utils.analysis_prompts.analysis_prompts_setting import master_document_phase_four
from app.routes.routes_CallAnalytics_Page.utils.analysis_prompts.analysis_prompts_setting import master_document_phase_four_a
from app.routes.routes_CallAnalytics_Page.utils.analysis_prompts.analysis_prompts_setting import master_document_phase_five
from app.routes.routes_CallAnalytics_Page.utils.analysis_prompts.analysis_prompts_setting import master_document_phase_six
from app.routes.routes_CallAnalytics_Page.utils.analysis_prompts.analysis_prompts_setting import master_document_phase_seven
from app.routes.routes_CallAnalytics_Page.utils.analysis_prompts.analysis_prompts_setting import master_document_phase_eight



DEFAULT_SALES_WORKFLOW_PHASES_SETTER = [
    {"name": "Rapport + Frame", "prompt": master_document_phase_one},
    {"name": "Find Tangible Problem", "prompt": master_document_phase_two}, 
    {"name": "Find Experience", "prompt": master_document_phase_three},
    {"name": "Portfolio Check", "prompt": master_document_phase_four},
    {"name": "Career Context & Income Replacement", "prompt": master_document_phase_four_a},
    {"name": "Probe, Time, Impact", "prompt": master_document_phase_five},
    {"name": "Financial Qualify", "prompt": master_document_phase_six},
    {"name": "Transition + Pitch", "prompt": master_document_phase_seven}
]


from app.routes.routes_CallAnalytics_Page.utils.analysis_prompts.analysis_prompts_closer import master_document_phase_one
from app.routes.routes_CallAnalytics_Page.utils.analysis_prompts.analysis_prompts_closer import master_document_phase_one_b
from app.routes.routes_CallAnalytics_Page.utils.analysis_prompts.analysis_prompts_closer import master_document_phase_two
from app.routes.routes_CallAnalytics_Page.utils.analysis_prompts.analysis_prompts_closer import master_document_phase_three
from app.routes.routes_CallAnalytics_Page.utils.analysis_prompts.analysis_prompts_closer import master_document_phase_four
from app.routes.routes_CallAnalytics_Page.utils.analysis_prompts.analysis_prompts_closer import master_document_phase_four_a
from app.routes.routes_CallAnalytics_Page.utils.analysis_prompts.analysis_prompts_closer import master_document_phase_five
from app.routes.routes_CallAnalytics_Page.utils.analysis_prompts.analysis_prompts_closer import master_document_phase_six
from app.routes.routes_CallAnalytics_Page.utils.analysis_prompts.analysis_prompts_closer import master_document_phase_seven
from app.routes.routes_CallAnalytics_Page.utils.analysis_prompts.analysis_prompts_closer import master_document_phase_eight
from app.routes.routes_CallAnalytics_Page.utils.analysis_prompts.analysis_prompts_closer import master_document_phase_nine
from app.routes.routes_CallAnalytics_Page.utils.analysis_prompts.analysis_prompts_closer import master_document_phase_ten
from app.routes.routes_CallAnalytics_Page.utils.analysis_prompts.analysis_prompts_closer import master_document_phase_eleven
from app.routes.routes_CallAnalytics_Page.utils.analysis_prompts.analysis_prompts_closer import master_document_phase_twelve
from app.routes.routes_CallAnalytics_Page.utils.analysis_prompts.analysis_prompts_closer import master_document_phase_thirteen
from app.routes.routes_CallAnalytics_Page.utils.analysis_prompts.analysis_prompts_closer import master_document_phase_fourteen
from app.routes.routes_CallAnalytics_Page.utils.analysis_prompts.analysis_prompts_closer import master_document_phase_fifteen
from app.routes.routes_CallAnalytics_Page.utils.analysis_prompts.analysis_prompts_closer import master_document_phase_sixteen
from app.routes.routes_CallAnalytics_Page.utils.analysis_prompts.analysis_prompts_closer import master_document_phase_seventeen


DEFAULT_SALES_WORKFLOW_PHASES_CLOSER = [
    {"name": "Phase 1: Rapport + Frame", "prompt": master_document_phase_one},
    {"name": "Phase 1B: Get Desired Outcome", "prompt": master_document_phase_one_b},
    {"name": "Phase 2: Find Tangible Problem", "prompt": master_document_phase_two},
    {"name": "Phase 3: Find Experience", "prompt": master_document_phase_three},
    {"name": "Phase 4: Portfolio Check", "prompt": master_document_phase_four},
    {"name": "Phase 4A: Career Context & Income Replacement", "prompt": master_document_phase_four_a},
    {"name": "Phase 5: Probe, Time, Impact", "prompt": master_document_phase_five},
    {"name": "Phase 6: Eliminate DIY Objection (Belief Shift)", "prompt": master_document_phase_six},
    {"name": "Phase 7: Alignment Phase", "prompt": master_document_phase_seven},
    {"name": "Phase 8: Success Phase", "prompt": master_document_phase_eight},
    {"name": "Phase 9: Desired State", "prompt": master_document_phase_nine},
    {"name": "Phase 10: Reality Check (Consequences of Inaction)", "prompt": master_document_phase_ten},
    {"name": "Phase 11: Pitch Transition (Commitment to North Star)", "prompt": master_document_phase_eleven},
    {"name": "Phase 12: Pillar 1 – Plug-and-Play Setup", "prompt": master_document_phase_twelve},
    {"name": "Phase 13: Pillar 2 – Deal Flow", "prompt": master_document_phase_thirteen},
    {"name": "Phase 14: Pillar 3 – Financing & Lending Access", "prompt": master_document_phase_fourteen},
    {"name": "Phase 15: Pillar 4 – Community, Coaching & Immersion", "prompt": master_document_phase_fifteen},
    {"name": "Phase 16: Commitment Phase", "prompt": master_document_phase_sixteen},
    {"name": "Phase 17: Objection Phase (Post-Pitch Only)", "prompt": master_document_phase_seventeen}
]

def get_default_workflow_name(company_name=None, workflow_type="setter"):
    """
    Generate a default workflow name based on company name and workflow type.
    
    Args:
        company_name (str, optional): The company name to include. Defaults to None.
        workflow_type (str, optional): The type of workflow ('setter' or 'closer'). Defaults to "setter".
        
    Returns:
        str: The generated workflow name
    """
    type_prefix = workflow_type.capitalize()
    if company_name:
        return f"{company_name} {type_prefix} Sales Workflow"
    else:
        return f"Default {type_prefix} Sales Workflow"

def get_default_workflow_description(workflow_type="setter"):
    """
    Get the default description for a new workflow based on its type.
    
    Args:
        workflow_type (str, optional): The type of workflow ('setter' or 'closer'). Defaults to "setter".
        
    Returns:
        str: The workflow description
    """
    if workflow_type == "setter":
        return "Default setter sales workflow for initial outreach and qualification"
    else:
        return "Default closer sales workflow for converting qualified leads to customers" 