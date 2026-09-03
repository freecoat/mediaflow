package it.mediaflow.atacroma.ui.vm

import androidx.lifecycle.ViewModel
import androidx.lifecycle.ViewModelProvider
import androidx.lifecycle.viewModelScope
import it.mediaflow.atacroma.data.local.StopEntity
import it.mediaflow.atacroma.data.model.Departure
import it.mediaflow.atacroma.data.model.ServiceAlert
import it.mediaflow.atacroma.data.repo.TransitRepository
import kotlinx.coroutines.Job
import kotlinx.coroutines.delay
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.launch

sealed interface StaticState {
    data object Loading : StaticState
    data class Ready(val stops: Int) : StaticState
    data class Error(val message: String) : StaticState
}

/** Factory generica basata su una lambda. */
class VmFactory(private val creator: () -> ViewModel) : ViewModelProvider.Factory {
    @Suppress("UNCHECKED_CAST")
    override fun <T : ViewModel> create(modelClass: Class<T>): T = creator() as T
}

class StopsViewModel(private val repo: TransitRepository) : ViewModel() {
    private val _static = MutableStateFlow<StaticState>(StaticState.Loading)
    val static: StateFlow<StaticState> = _static.asStateFlow()

    private val _query = MutableStateFlow("")
    val query: StateFlow<String> = _query.asStateFlow()

    private val _results = MutableStateFlow<List<StopEntity>>(emptyList())
    val results: StateFlow<List<StopEntity>> = _results.asStateFlow()

    private val _nearby = MutableStateFlow<List<StopEntity>>(emptyList())
    val nearby: StateFlow<List<StopEntity>> = _nearby.asStateFlow()

    private var searchJob: Job? = null

    init {
        ensureStatic()
    }

    fun ensureStatic() {
        viewModelScope.launch {
            _static.value = StaticState.Loading
            runCatching { repo.ensureStaticData() }
                .onSuccess { _static.value = StaticState.Ready(it) }
                .onFailure { _static.value = StaticState.Error(it.message ?: "Errore") }
        }
    }

    fun refreshStatic() {
        viewModelScope.launch {
            _static.value = StaticState.Loading
            runCatching { repo.refreshStaticData() }
                .onSuccess { _static.value = StaticState.Ready(it); onQueryChange(_query.value) }
                .onFailure { _static.value = StaticState.Error(it.message ?: "Errore") }
        }
    }

    fun onQueryChange(q: String) {
        _query.value = q
        searchJob?.cancel()
        if (q.isBlank()) {
            _results.value = emptyList()
            return
        }
        searchJob = viewModelScope.launch {
            delay(200)
            runCatching { repo.searchStops(q) }.onSuccess { _results.value = it }
        }
    }

    fun loadNearby(lat: Double, lon: Double) {
        viewModelScope.launch {
            runCatching { repo.nearbyStops(lat, lon) }.onSuccess { _nearby.value = it }
        }
    }
}

class DeparturesViewModel(
    private val repo: TransitRepository,
    private val stopId: String,
) : ViewModel() {
    private val _stopName = MutableStateFlow("")
    val stopName: StateFlow<String> = _stopName.asStateFlow()

    private val _departures = MutableStateFlow<List<Departure>>(emptyList())
    val departures: StateFlow<List<Departure>> = _departures.asStateFlow()

    private val _loading = MutableStateFlow(false)
    val loading: StateFlow<Boolean> = _loading.asStateFlow()

    private val _error = MutableStateFlow<String?>(null)
    val error: StateFlow<String?> = _error.asStateFlow()

    private val _updatedAt = MutableStateFlow(0L)
    val updatedAt: StateFlow<Long> = _updatedAt.asStateFlow()

    init {
        viewModelScope.launch { _stopName.value = repo.stopById(stopId)?.name ?: stopId }
        refresh()
    }

    fun refresh() {
        viewModelScope.launch {
            _loading.value = true
            _error.value = null
            runCatching { repo.departures(stopId) }
                .onSuccess { _departures.value = it; _updatedAt.value = System.currentTimeMillis() }
                .onFailure { _error.value = it.message ?: "Errore" }
            _loading.value = false
        }
    }
}

class AlertsViewModel(private val repo: TransitRepository) : ViewModel() {
    private val _alerts = MutableStateFlow<List<ServiceAlert>>(emptyList())
    val alerts: StateFlow<List<ServiceAlert>> = _alerts.asStateFlow()

    private val _loading = MutableStateFlow(false)
    val loading: StateFlow<Boolean> = _loading.asStateFlow()

    private val _error = MutableStateFlow<String?>(null)
    val error: StateFlow<String?> = _error.asStateFlow()

    init {
        refresh()
    }

    fun refresh() {
        viewModelScope.launch {
            _loading.value = true
            _error.value = null
            runCatching { repo.alerts() }
                .onSuccess { _alerts.value = it }
                .onFailure { _error.value = it.message ?: "Errore" }
            _loading.value = false
        }
    }
}
