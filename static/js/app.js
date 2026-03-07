const { createApp } = Vue;

createApp({
  data() {
    return {
      isLoggedIn: false,
      user: {},
      view: 'dashboard',
      tab: 'login',
      authError: '',
      toast: '',
      // login/register forms
      lf: { username:'', password:'' },
      rf: { username:'', email:'', phone:'', address:'', date_of_birth:'', gender:'', blood_group:'', password:'' },
      // shared data
      departments: [],
      doctors: [],
      patients: [],
      appointments: [],
      treatments: [],
      availability: [],
      // admin stats
      stats: { total_doctors:0, total_patients:0, total_appointments:0, upcoming_appointments:0 },
      // search
      doctorSearch: '',
      patientSearch: '',
      deptFilter: '',
      apptFilter: '',
      // doctor dashboard
      doctorDash: { today_appointments:[], week_appointments:[], total_patients:0 },
      doctorPatients: [],
      // modals
      showDoctorModal: false,
      showPatientEditModal: false,
      showDeptModal: false,
      showBookModal: false,
      showTreatModal: false,
      showRescheduleModal: false,
      showAvailModal: false,
      showPayModal: false,
      // forms
      doctorForm: { username:'', email:'', phone:'', bio:'', specialization_id:'', password:'', is_available:true },
      editingDoctorId: null,
      patientForm: { username:'', email:'', phone:'', address:'' },
      editingPatientId: null,
      deptForm: { name:'', description:'' },
      bookForm: { doctor_id:'', appointment_date:'', appointment_time:'', reason:'' },
      bookingDoctor: null,
      treatForm: { diagnosis:'', prescription:'', notes:'', next_visit:'', appointment_id:null },
      treatingAppt: null,
      reschedForm: { appointment_date:'', appointment_time:'', appointment_id:null },
      availForm: { start_date:'', start_time:'09:00', end_time:'17:00' },
      payForm: { appointment_id:'', card_number:'', expiry:'', cvv:'', amount:590 },
      payResult: '',
      // profile
      profileForm: { username:'', email:'', phone:'', date_of_birth:'', gender:'', blood_group:'', address:'', password:'' },
      // export
      exporting: false,
      exportMsg: '',
    };
  },

  computed: {
    filteredDoctors() {
      let list = this.doctors;
      if (this.doctorSearch) list = list.filter(d => d.username.toLowerCase().includes(this.doctorSearch.toLowerCase()) || (d.specialization||'').toLowerCase().includes(this.doctorSearch.toLowerCase()));
      if (this.deptFilter) list = list.filter(d => d.specialization === this.deptFilter);
      return list;
    },
    filteredPatients() {
      if (!this.patientSearch) return this.patients;
      const q = this.patientSearch.toLowerCase();
      return this.patients.filter(p => p.username.toLowerCase().includes(q) || (p.email||'').toLowerCase().includes(q) || (p.phone||'').includes(q));
    },
    filteredAppointments() {
      if (!this.apptFilter) return this.appointments;
      return this.appointments.filter(a => a.status === this.apptFilter);
    },
    today() { return new Date().toISOString().split('T')[0]; }
  },

  methods: {
    showToast(msg) {
      this.toast = msg;
      setTimeout(() => { this.toast = ''; }, 3500);
    },
    statusBadge(s) {
      if (s === 'Completed') return 'bg-success';
      if (s === 'Booked') return 'bg-warning text-dark';
      return 'bg-danger';
    },

    // AUTH
    async doLogin() {
      this.authError = '';
      try {
        const r = await axios.post('/api/login', this.lf);
        this.user = r.data.user;
        this.isLoggedIn = true;
        this.view = 'dashboard';
        await this.loadAll();
      } catch(e) { this.authError = e.response?.data?.error || 'Login failed'; }
    },
    async doRegister() {
      this.authError = '';
      try {
        await axios.post('/api/register', this.rf);
        this.showToast('Account created! Please login.');
        this.tab = 'login';
        this.lf.username = this.rf.username;
      } catch(e) { this.authError = e.response?.data?.error || 'Registration failed'; }
    },
    async doLogout() {
      await axios.post('/api/logout');
      this.isLoggedIn = false;
      this.user = {};
      this.view = 'dashboard';
    },

    // LOAD DATA
    async loadAll() {
      if (this.user.role === 'admin') {
        await Promise.all([this.loadStats(), this.loadDoctors(), this.loadPatients(), this.loadAppointments(), this.loadDepts()]);
      } else if (this.user.role === 'doctor') {
        await Promise.all([this.loadDoctorDash(), this.loadAppointments(), this.loadDoctorPatients(), this.loadAvailability()]);
      } else if (this.user.role === 'patient') {
        await Promise.all([this.loadDepts(), this.loadDoctors(), this.loadAppointments(), this.loadTreatments()]);
      }
    },
    async loadStats() {
      const r = await axios.get('/api/dashboard/stats');
      this.stats = r.data;
    },
    async loadDoctors() {
      const r = await axios.get('/api/doctors');
      this.doctors = r.data;
    },
    async loadPatients() {
      const r = await axios.get('/api/patients');
      this.patients = r.data;
    },
    async loadAppointments() {
      const r = await axios.get('/api/appointments');
      this.appointments = r.data;
    },
    async loadDepts() {
      const r = await axios.get('/api/departments');
      this.departments = r.data;
    },
    async loadTreatments() {
      const r = await axios.get('/api/treatments');
      this.treatments = r.data;
    },
    async loadDoctorDash() {
      const r = await axios.get('/api/doctor/dashboard');
      this.doctorDash = r.data;
    },
    async loadDoctorPatients() {
      const r = await axios.get('/api/doctor/patients');
      this.doctorPatients = r.data;
    },
    async loadAvailability() {
      const r = await axios.get('/api/availability?doctor_id=' + this.user.id);
      this.availability = r.data;
    },
    async navTo(v) {
      this.view = v;
      if (v === 'dashboard') {
        if (this.user.role === 'admin') { await this.loadStats(); await this.loadAppointments(); }
        else if (this.user.role === 'doctor') { await this.loadDoctorDash(); }
        else { await this.loadDepts(); await this.loadAppointments(); }
      } else if (v === 'doctors') { await this.loadDoctors(); if (this.user.role === 'admin') await this.loadDepts(); }
      else if (v === 'patients') { await this.loadPatients(); }
      else if (v === 'appointments') { await this.loadAppointments(); }
      else if (v === 'departments') { await this.loadDepts(); }
      else if (v === 'mypatients') { await this.loadDoctorPatients(); }
      else if (v === 'availability') { await this.loadAvailability(); }
      else if (v === 'history') { await this.loadTreatments(); await this.loadAppointments(); }
      else if (v === 'profile') { this.profileForm = { username:this.user.username, email:this.user.email, phone:this.user.phone||'', date_of_birth:this.user.date_of_birth||'', gender:this.user.gender||'', blood_group:this.user.blood_group||'', address:this.user.address||'', password:'' }; }
      else if (v === 'finddoctors') { await this.loadDoctors(); await this.loadDepts(); }
      else if (v === 'payment') { await this.loadAppointments(); }
    },

    // DOCTORS CRUD
    openAddDoctor() {
      this.editingDoctorId = null;
      this.doctorForm = { username:'', email:'', phone:'', bio:'', specialization_id:'', password:'', is_available:true };
      this.showDoctorModal = true;
    },
    openEditDoctor(d) {
      this.editingDoctorId = d.id;
      this.doctorForm = { username:d.username, email:d.email, phone:d.phone||'', bio:d.bio||'', specialization_id:d.specialization_id||'', password:'', is_available:d.is_available };
      this.showDoctorModal = true;
    },
    async saveDoctor() {
      try {
        if (this.editingDoctorId) await axios.put('/api/doctors/' + this.editingDoctorId, this.doctorForm);
        else await axios.post('/api/doctors', this.doctorForm);
        this.showDoctorModal = false;
        await this.loadDoctors();
        await this.loadStats();
        this.showToast('Doctor saved successfully.');
      } catch(e) { alert(e.response?.data?.error || 'Error saving doctor'); }
    },
    async deleteDoctor(id) {
      if (!confirm('Delete this doctor?')) return;
      await axios.delete('/api/doctors/' + id);
      await this.loadDoctors();
      await this.loadStats();
      this.showToast('Doctor removed.');
    },

    // PATIENTS CRUD
    openEditPatient(p) {
      this.editingPatientId = p.id;
      this.patientForm = { username:p.username, email:p.email, phone:p.phone||'', address:p.address||'' };
      this.showPatientEditModal = true;
    },
    async savePatient() {
      await axios.put('/api/patients/' + this.editingPatientId, this.patientForm);
      this.showPatientEditModal = false;
      await this.loadPatients();
      this.showToast('Patient updated.');
    },
    async deletePatient(id) {
      if (!confirm('Remove this patient?')) return;
      await axios.delete('/api/patients/' + id);
      await this.loadPatients();
      await this.loadStats();
      this.showToast('Patient removed.');
    },

    // DEPARTMENTS
    async addDept() {
      await axios.post('/api/departments', this.deptForm);
      this.showDeptModal = false;
      await this.loadDepts();
      this.showToast('Department added.');
    },

    // APPOINTMENTS
    openBookModal(doctor) {
      this.bookingDoctor = doctor;
      this.bookForm = { doctor_id: doctor.id, appointment_date:'', appointment_time:'', reason:'' };
      this.showBookModal = true;
    },
    async bookAppointment() {
      try {
        await axios.post('/api/appointments', this.bookForm);
        this.showBookModal = false;
        await this.loadAppointments();
        this.showToast('Appointment booked!');
      } catch(e) { alert(e.response?.data?.error || 'Error booking'); }
    },
    async cancelAppointment(id) {
      if (!confirm('Cancel this appointment?')) return;
      await axios.delete('/api/appointments/' + id);
      await this.loadAppointments();
      if (this.user.role === 'doctor') await this.loadDoctorDash();
      this.showToast('Appointment cancelled.');
    },
    async updateApptStatus(id, status) {
      await axios.put('/api/appointments/' + id, { status });
      await this.loadAppointments();
      if (this.user.role === 'doctor') await this.loadDoctorDash();
      this.showToast('Status updated to ' + status);
    },
    openReschedule(a) {
      this.reschedForm = { appointment_id: a.id, appointment_date:'', appointment_time:'' };
      this.showRescheduleModal = true;
    },
    async confirmReschedule() {
      try {
        await axios.put('/api/appointments/' + this.reschedForm.appointment_id + '/reschedule', { appointment_date: this.reschedForm.appointment_date, appointment_time: this.reschedForm.appointment_time });
        this.showRescheduleModal = false;
        await this.loadAppointments();
        this.showToast('Appointment rescheduled.');
      } catch(e) { alert(e.response?.data?.error || 'Error rescheduling'); }
    },

    // TREATMENTS
    openTreatModal(a) {
      this.treatingAppt = a;
      this.treatForm = { diagnosis:'', prescription:'', notes:'', next_visit:'', appointment_id: a.id };
      this.showTreatModal = true;
    },
    async saveTreatment() {
      if (!this.treatForm.diagnosis) { alert('Diagnosis is required.'); return; }
      await axios.post('/api/treatments', this.treatForm);
      this.showTreatModal = false;
      await this.loadDoctorDash();
      await this.loadAppointments();
      this.showToast('Treatment saved.');
    },
    getDoctorName(aptId) {
      const a = this.appointments.find(x => x.id === aptId);
      return a ? a.doctor_name : '';
    },

    // AVAILABILITY
    async setAvailability() {
      const start = new Date(this.availForm.start_date);
      const end = new Date(start);
      end.setDate(end.getDate() + 6);
      await axios.post('/api/availability/bulk', {
        start_date: start.toISOString().split('T')[0],
        end_date: end.toISOString().split('T')[0],
        start_time: this.availForm.start_time,
        end_time: this.availForm.end_time
      });
      await this.loadAvailability();
      this.showToast('Availability set for 7 days.');
    },

    // PROFILE
    async saveProfile() {
      await axios.put('/api/patients/' + this.user.id, this.profileForm);
      this.user.username = this.profileForm.username;
      this.showToast('Profile updated.');
    },

    // CSV EXPORT
    async triggerExport() {
      this.exporting = true;
      this.exportMsg = 'Export started...';
      const r = await axios.post('/api/export/csv');
      const taskId = r.data.task_id;
      const poll = setInterval(async () => {
        const s = await axios.get('/api/export/status/' + taskId);
        if (s.data.status === 'completed') {
          clearInterval(poll);
          this.exporting = false;
          this.exportMsg = 'Export complete! CSV is ready.';
          this.showToast('CSV Export completed!');
        }
      }, 2000);
    },

    // PAYMENT
    async processPayment() {
      const r = await axios.post('/api/payments', this.payForm);
      this.payResult = 'Payment successful! Transaction ID: ' + r.data.transaction_id;
      this.showToast('Payment processed!');
    },

    // SEARCH
    async searchDoctors() {
      const r = await axios.get('/api/doctors?search=' + this.doctorSearch);
      this.doctors = r.data;
    },
    async searchPatients() {
      const r = await axios.get('/api/patients?search=' + this.patientSearch);
      this.patients = r.data;
    },
  },

  async mounted() {
    try {
      const r = await axios.get('/api/current-user');
      this.user = r.data.user;
      this.isLoggedIn = true;
      await this.loadAll();
    } catch(e) { this.isLoggedIn = false; }
  }
}).mount('#hms');
</script>
</body>
</html>
