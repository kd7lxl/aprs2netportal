from django import forms
from django.contrib.auth import get_user_model

from .models import Server

User = get_user_model()


class SysopServerForm(forms.ModelForm):
    """Allows sysops to edit their server details. Some fields are readonly."""

    # Only administrators may change these, through the admin site.
    ADMIN_ONLY_FIELDS = ('server_id', 'hostname', 'domain')

    class Meta:
        model = Server
        fields = '__all__'

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        if self.instance and self.instance.pk:
            for name in self.ADMIN_ONLY_FIELDS:
                # A disabled field ignores submitted data and keeps the
                # instance's value.
                self.fields[name].disabled = True
                self.fields[name].required = False

        self.fields['authorized_sysops'].widget.attrs['size'] = "10"
        user_qs = User.objects.order_by('username')
        self.fields['authorized_sysops'].queryset = user_qs
        self.fields['owner'].queryset = user_qs


class UserForm(forms.ModelForm):
    class Meta:
        model = User
        fields = ['first_name', 'last_name', 'email']
