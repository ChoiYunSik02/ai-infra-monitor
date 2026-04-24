class LocalDBRouter:
    LOCAL_MODELS = {'chatmessage'}

    def db_for_read(self, model, **hints):
        if model._meta.model_name in self.LOCAL_MODELS:
            return 'local'
        return None

    def db_for_write(self, model, **hints):
        if model._meta.model_name in self.LOCAL_MODELS:
            return 'local'
        return None

    def allow_migrate(self, db, app_label, model_name=None, **hints):
        if model_name in self.LOCAL_MODELS:
            return db == 'local'
        if app_label == 'monitor':
            return db == 'default'
        return None
