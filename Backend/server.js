// server.js
const express = require('express');
const mongoose = require('mongoose');
const cors = require('cors');   // <-- import cors
const app = express();
const User = require('./model/user');

app.use(express.json());

// ✅ Enable CORS (allow frontend requests)
app.use(cors({
  origin: "http://localhost:5173",  // React (Vite) frontend
  methods: ["GET", "POST", "PUT", "DELETE"],
  credentials: true
}));

// Test route
app.get('/', (req, res) => {
  res.send('Server is running!');
});

// MongoDB connection
mongoose.connect('mongodb+srv://dvvsatyanarayana3628:12345@cluster0.ken3nof.mongodb.net/Lumen?retryWrites=true&w=majority&appName=Cluster0', {
  useNewUrlParser: true,
  useUnifiedTopology: true,
})
.then(() => console.log('MongoDB connected'))
.catch(err => console.log('MongoDB connection error:', err));

const PORT = process.env.PORT || 3000;
app.listen(PORT, () => console.log(`Server running on port ${PORT}`));

// Create a new user
app.post('/users', async (req, res) => {
  try {
    const { name, email, password, mobileNo } = req.body;  // <--- expects JSON body
    const user = new User({ name, email, password, mobileNo });
    await user.save();
    res.status(201).json({ message: 'User created successfully', user });
  } catch (err) {
    res.status(400).json({ error: err.message });
  }
});
