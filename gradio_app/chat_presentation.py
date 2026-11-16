"""Short chat with optional detail and bounded, user-operated choice cards."""
from pydantic import BaseModel, ConfigDict, Field, model_validator


class Choice(BaseModel):
    model_config = ConfigDict(extra='forbid')
    label: str = Field(min_length=1,max_length=80)
    value: str = Field(min_length=1,max_length=600)

    @model_validator(mode='after')
    def no_implicit_approval(self):
        from .chat_confirmations import is_confirmation
        if is_confirmation(self.value):
            raise ValueError('Approval belongs to the exact confirmation card, not a generic question option.')
        return self


PHYSICS_CHOICES = [
    {'label':'Mechanical','value':'Mechanical'},
    {'label':'Heat transfer','value':'Heat transfer'},
    {'label':'Fluid dynamics','value':'Fluid dynamics'}]
DOMAIN_CHOICES = [
    {'label':'Existing fluid volume','value':'The uploaded CAD is already the actual fluid volume.'},
    {'label':'Box around obstacle','value':'Add a box enclosure around the uploaded solid obstacle.'},
    {'label':'Cylinder / pipe','value':'Use a cylindrical or pipe fluid domain. Help me specify its dimensions and CAD role.'},
    {'label':'Other technique','value':'I want another fluid-domain technique. Ask me which one.'}]


def compact(text,details=None):
    """Legacy/model verbosity remains recoverable instead of being discarded."""
    if len(text) <= 350:
        return text,details
    first = text.split('\n\n',1)[0]
    if len(first) > 300:
        end = text.rfind('. ',0,280)
        first = text[:end+1] if end > 40 else text[:280].rstrip()+'…'
    return first,'\n\n'.join(v for v in (text,details) if v)
