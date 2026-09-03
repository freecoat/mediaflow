package it.mediaflow.atacroma

import android.app.Application
import it.mediaflow.atacroma.data.local.AppDatabase
import it.mediaflow.atacroma.data.repo.TransitRepository

class AtacApp : Application() {
    lateinit var repository: TransitRepository
        private set

    override fun onCreate() {
        super.onCreate()
        repository = TransitRepository(AppDatabase.get(this))
    }
}
